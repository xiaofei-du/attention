// Native speech playback and temporary media attenuation. No microphone input.
#import <Foundation/Foundation.h>
#import <AVFAudio/AVFAudio.h>
#import "duck.h"
#include <math.h>
#include <signal.h>
#include <stdio.h>
#include <unistd.h>

static volatile sig_atomic_t interrupted = 0;
static void interrupt_handler(int value) { (void)value; interrupted = 1; }

@interface PlaybackResult : NSObject <AVAudioPlayerDelegate>
@property(nonatomic) BOOL finished;
@property(nonatomic) BOOL succeeded;
@end
@implementation PlaybackResult
- (void)audioPlayerDidFinishPlaying:(AVAudioPlayer *)player successfully:(BOOL)flag {
    (void)player;
    self.finished = YES;
    self.succeeded = flag;
}
- (void)audioPlayerDecodeErrorDidOccur:(AVAudioPlayer *)player error:(NSError *)error {
    (void)player;
    fprintf(stderr, "audio decode error: %s\n", error.localizedDescription.UTF8String);
    self.finished = YES;
    self.succeeded = NO;
}
@end

static int failure(const char *operation, NSError *error) {
    fprintf(stderr, "%s: %s\n", operation,
        error ? error.localizedDescription.UTF8String : "operation failed");
    return 1;
}

static void pump(void) {
    [[NSRunLoop currentRunLoop] runUntilDate:[NSDate dateWithTimeIntervalSinceNow:0.05]];
}

int main(int argc, const char *argv[]) {
    @autoreleasepool {
        if (argc == 2 && !strcmp(argv[1], "--output-info")) {
            NSError *infoError = nil;
            NSDictionary *info = [NKCDucker outputInfo:&infoError];
            if (!info) return failure("inspect output", infoError);
            NSData *data = [NSJSONSerialization dataWithJSONObject:info options:0 error:&infoError];
            puts([[NSString alloc] initWithData:data encoding:NSUTF8StringEncoding].UTF8String);
            return 0;
        }
        BOOL inspect = argc == 3 && !strcmp(argv[1], "--inspect");
        BOOL duckTest = (argc == 3 || argc == 4) && !strcmp(argv[1], "--duck-test");
        BOOL duck = duckTest || ((argc == 3 || argc == 4) && !strcmp(argv[1], "--duck"));
        if (argc != 2 && !inspect && !duck) {
            fprintf(stderr, "Usage: nkc-player [--inspect | --duck | --duck-test] AUDIO_FILE [MEDIA_GAIN] | --output-info\n");
            return 2;
        }
        float mediaGain = 0.05f;
        if (duck && argc == 4) {
            char *end = NULL;
            mediaGain = strtof(argv[3], &end);
            if (end == argv[3] || *end || !isfinite(mediaGain) || mediaGain <= 0 || mediaGain > 1) {
                fprintf(stderr, "media gain must be a number greater than zero and at most one\n");
                return 2;
            }
        }
        NSURL *url = [NSURL fileURLWithPath:[NSString stringWithUTF8String:argv[(inspect || duck) ? 2 : 1]]];
        NSError *error = nil;
        AVAudioFile *file = [[AVAudioFile alloc] initForReading:url
            commonFormat:AVAudioPCMFormatFloat32 interleaved:NO error:&error];
        if (!file) return failure("open audio file", error);
        double duration = file.length / file.processingFormat.sampleRate;
        if (!isfinite(duration) || duration <= 0 || duration > 120) {
            fprintf(stderr, "audio duration must be greater than zero and at most 120 seconds\n");
            return 1;
        }
        if (inspect) {
            AVAudioPCMBuffer *buffer = [[AVAudioPCMBuffer alloc]
                initWithPCMFormat:file.processingFormat frameCapacity:4096];
            if (!buffer) return failure("allocate decode buffer", nil);
            double power = 0;
            unsigned long long samples = 0;
            while (file.framePosition < file.length) {
                if (![file readIntoBuffer:buffer error:&error]) return failure("decode audio", error);
                if (!buffer.frameLength) break;
                for (AVAudioChannelCount c = 0; c < buffer.format.channelCount; ++c)
                    for (AVAudioFrameCount i = 0; i < buffer.frameLength; ++i) {
                        double value = buffer.floatChannelData[c][i];
                        power += value * value;
                        samples++;
                    }
            }
            printf("{\"duration\":%.6f,\"rms\":%.6f}\n", duration, samples ? sqrt(power / samples) : 0);
            return 0;
        }
        file = nil;
        signal(SIGTERM, interrupt_handler);
        signal(SIGINT, interrupt_handler);
        pid_t owner = getppid();
        PlaybackResult *completion = [PlaybackResult new];
        AVAudioPlayer *player = [[AVAudioPlayer alloc] initWithContentsOfURL:url error:&error];
        if (!player) return failure("prepare audio player", error);
        player.delegate = completion;
        player.volume = 1.0;
        if (![player prepareToPlay]) return failure("prepare audio output", nil);
        if (interrupted || getppid() != owner) return 130;
        NKCDucker *ducker = nil;
        if (duck) {
            fprintf(stderr, "media-relay: requires system-audio permission; microphone=unused\n");
            ducker = [NKCDucker new];
            if (![ducker startWithGain:mediaGain error:&error]) {
                [ducker stop];
                failure("media relay unavailable before playback", error);
                return (interrupted || getppid() != owner) ? 130 : 75;
            }
            NSDate *readyDeadline = [NSDate dateWithTimeIntervalSinceNow:1.0];
            while (![ducker receivedMedia] && [ducker healthy] && !interrupted &&
                   getppid() == owner && readyDeadline.timeIntervalSinceNow > 0) pump();
            if ((duckTest && ![ducker receivedMedia]) || ![ducker healthy] || interrupted || getppid() != owner) {
                [ducker stop];
                failure("No usable media signal; relay stopped. Check system-audio permission and play some media before testing", nil);
                return (interrupted || getppid() != owner) ? 130 : 75;
            }
            fprintf(stderr, "media-relay-started; gain=%.3f; live-signal=%d\n", mediaGain, [ducker receivedMedia]);
        }
        BOOL started = NO;
        if (!interrupted && getppid() == owner) started = [player play];
        NSDate *deadline = [NSDate dateWithTimeIntervalSinceNow:duration + 5];
        while (started && !completion.finished && !interrupted && getppid() == owner &&
               (!ducker || [ducker healthy]) && deadline.timeIntervalSinceNow > 0)
            pump();
        int result;
        if (interrupted || getppid() != owner) result = 130;
        else if (ducker && ![ducker healthy]) result = failure("Audio route or relay format changed; stopping test", nil);
        else if (!started) result = failure("start audio player", nil);
        else if (!completion.finished) result = failure("audio playback timeout", nil);
        else if (!completion.succeeded) result = failure("finish audio playback", nil);
        else result = 0;
        [player stop];
        player = nil;
        [ducker stop];
        fprintf(stderr, "playback-ended; relay-stopped=%d; completed=%d; result=%d\n",
                duck, completion.finished && completion.succeeded, result);
        return result;
    }
}
