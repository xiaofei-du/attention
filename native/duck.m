#import "duck.h"
#import <CoreAudio/CoreAudio.h>
#import <CoreAudio/AudioHardwareTapping.h>
#import <CoreAudio/CATapDescription.h>
#include "relay.h"
#include <stdatomic.h>
#include <unistd.h>

typedef struct {
    atomic_bool fault;
    atomic_bool receivedMedia;
    float gain;
} RelayState;

static OSStatus read_property(AudioObjectID object, AudioObjectPropertySelector selector,
                              AudioObjectPropertyScope scope, UInt32 size, void *value) {
    AudioObjectPropertyAddress address = {selector, scope, kAudioObjectPropertyElementMain};
    return AudioObjectGetPropertyData(object, &address, 0, NULL, &size, value);
}

static BOOL problem(NSError **error, NSString *message, OSStatus status) {
    if (error) *error = [NSError errorWithDomain:@"NoKeyboardCode.Audio" code:status ?: 1
        userInfo:@{NSLocalizedDescriptionKey: [NSString stringWithFormat:@"%@ (%d)", message, (int)status]}];
    return NO;
}

static UInt32 stream_count(AudioObjectID device, AudioObjectPropertyScope scope) {
    AudioObjectPropertyAddress address = {kAudioDevicePropertyStreams, scope, kAudioObjectPropertyElementMain};
    UInt32 size = 0;
    return AudioObjectGetPropertyDataSize(device, &address, 0, NULL, &size) == noErr
        ? size / sizeof(AudioStreamID) : UINT32_MAX;
}

static BOOL stream_format(AudioObjectID device, AudioObjectPropertyScope scope, AudioStreamBasicDescription *format) {
    AudioStreamID stream = 0;
    return stream_count(device, scope) == 1 &&
        read_property(device, kAudioDevicePropertyStreams, scope, sizeof(stream), &stream) == noErr &&
        read_property(stream, kAudioStreamPropertyVirtualFormat, kAudioObjectPropertyScopeGlobal,
                      sizeof(*format), format) == noErr;
}

static BOOL supported(AudioStreamBasicDescription format) {
    return format.mFormatID == kAudioFormatLinearPCM &&
        (format.mFormatFlags & kAudioFormatFlagIsFloat) &&
        !(format.mFormatFlags & (kAudioFormatFlagIsBigEndian | kAudioFormatFlagIsNonInterleaved)) &&
        format.mBitsPerChannel == 32 && format.mChannelsPerFrame >= 1 && format.mChannelsPerFrame <= 2 &&
        format.mBytesPerFrame == sizeof(float) * format.mChannelsPerFrame &&
        format.mSampleRate > 0;
}

static BOOL equal_format(AudioStreamBasicDescription a, AudioStreamBasicDescription b) {
    return supported(a) && supported(b) && a.mSampleRate == b.mSampleRate &&
        a.mChannelsPerFrame == b.mChannelsPerFrame && a.mBytesPerFrame == b.mBytesPerFrame;
}

static AudioDeviceID default_output(void) {
    AudioDeviceID device = 0;
    read_property(kAudioObjectSystemObject, kAudioHardwarePropertyDefaultOutputDevice,
                  kAudioObjectPropertyScopeGlobal, sizeof(device), &device);
    return device;
}

static OSStatus relay_audio(AudioDeviceID device, const AudioTimeStamp *now,
    const AudioBufferList *input, const AudioTimeStamp *inputTime,
    AudioBufferList *output, const AudioTimeStamp *outputTime, void *context) {
    (void)device; (void)now; (void)inputTime; (void)outputTime;
    RelayState *state = context;
    if (!nkc_relay(input, output, state->gain)) {
        atomic_store_explicit(&state->fault, true, memory_order_relaxed);
        return noErr;
    }
    // Only a boolean is retained: no recording, media text, or media samples.
    if (!atomic_load_explicit(&state->receivedMedia, memory_order_relaxed)) {
        for (UInt32 b = 0; b < input->mNumberBuffers; b++) {
            const float *samples = input->mBuffers[b].mData;
            for (UInt32 s = 0; s < input->mBuffers[b].mDataByteSize / sizeof(float); s++)
                if (fabsf(samples[s]) > 0.00001f) {
                    atomic_store_explicit(&state->receivedMedia, true, memory_order_relaxed);
                    return noErr;
                }
        }
    }
    return noErr;
}

@implementation NKCDucker {
    AudioObjectID _tap;
    AudioDeviceID _aggregate;
    AudioDeviceID _output;
    AudioDeviceIOProcID _io;
    BOOL _started;
    RelayState _state;
}

+ (NSDictionary *)outputInfo:(NSError **)error {
    AudioDeviceID device = default_output();
    CFStringRef name = NULL;
    AudioStreamBasicDescription format = {0};
    if (!device || read_property(device, kAudioObjectPropertyName, kAudioObjectPropertyScopeGlobal,
                                sizeof(name), &name) != noErr) {
        problem(error, @"Read default output", 0);
        return nil;
    }
    BOOL formatOK = stream_format(device, kAudioObjectPropertyScopeOutput, &format) && supported(format);
    return @{@"device": @(device), @"name": CFBridgingRelease(name),
             @"inputStreams": @(stream_count(device, kAudioObjectPropertyScopeInput)),
             @"outputStreams": @(stream_count(device, kAudioObjectPropertyScopeOutput)),
             @"sampleRate": @(format.mSampleRate), @"channels": @(format.mChannelsPerFrame),
             @"supportedForTest": @(formatOK && stream_count(device, kAudioObjectPropertyScopeInput) == 0)};
}

- (BOOL)startWithGain:(float)gain error:(NSError **)error {
    if (!isfinite(gain) || gain <= 0 || gain > 1) return problem(error, @"Invalid media gain", 0);
    if (_tap || _aggregate) return problem(error, @"Ducker already started", 0);
    _output = default_output();
    AudioStreamBasicDescription outputFormat = {0}, tapFormat = {0}, inFormat = {0}, outFormat = {0};
    // This prototype refuses devices with physical inputs. It must never start
    // a microphone as an accidental member of an aggregate device.
    if (!_output || stream_count(_output, kAudioObjectPropertyScopeInput) != 0 ||
        !stream_format(_output, kAudioObjectPropertyScopeOutput, &outputFormat) || !supported(outputFormat))
        return problem(error, @"Test requires an output-only mono/stereo Float32 device, such as Mac speakers", 0);
    CFStringRef deviceUID = NULL;
    OSStatus status = read_property(_output, kAudioDevicePropertyDeviceUID, kAudioObjectPropertyScopeGlobal,
                                   sizeof(deviceUID), &deviceUID);
    if (status || !deviceUID) return problem(error, @"Read output UID", status);
    NSString *uid = CFBridgingRelease(deviceUID);
    pid_t pid = getpid();
    AudioObjectID process = 0;
    UInt32 size = sizeof(process);
    AudioObjectPropertyAddress address = {kAudioHardwarePropertyTranslatePIDToProcessObject,
        kAudioObjectPropertyScopeGlobal, kAudioObjectPropertyElementMain};
    status = AudioObjectGetPropertyData(kAudioObjectSystemObject, &address, sizeof(pid), &pid, &size, &process);
    // prepareToPlay has connected this process before creating the tap.
    if (status || !process) return problem(error, @"Cannot exclude the speech player from media capture", status);
    CATapDescription *description = [[CATapDescription alloc] initExcludingProcesses:@[@(process)]
        andDeviceUID:uid withStream:0];
    description.name = @"No Keyboard Code temporary media volume";
    description.privateTap = YES;
    description.muteBehavior = CATapMutedWhenTapped;
    if (@available(macOS 26.0, *)) {
        NSString *bundleID = NSBundle.mainBundle.bundleIdentifier;
        if (bundleID) description.bundleIDs = @[bundleID];
    }
    status = AudioHardwareCreateProcessTap(description, &_tap);
    if (status) return problem(error, @"Create system-audio tap", status);
    status = read_property(_tap, kAudioTapPropertyFormat, kAudioObjectPropertyScopeGlobal,
                           sizeof(tapFormat), &tapFormat);
    if (status || !equal_format(outputFormat, tapFormat)) {
        [self stop];
        return problem(error, @"Unsupported tap format; media unchanged", status);
    }
    NSDictionary *configuration = @{
        @kAudioAggregateDeviceNameKey: @"No Keyboard Code temporary relay",
        @kAudioAggregateDeviceUIDKey: NSUUID.UUID.UUIDString,
        @kAudioAggregateDeviceIsPrivateKey: @YES,
        @kAudioAggregateDeviceIsStackedKey: @NO,
        @kAudioAggregateDeviceMainSubDeviceKey: uid,
        @kAudioAggregateDeviceSubDeviceListKey: @[@{@kAudioSubDeviceUIDKey: uid}],
        @kAudioAggregateDeviceTapListKey: @[@{@kAudioSubTapUIDKey: description.UUID.UUIDString,
                                            @kAudioSubTapDriftCompensationKey: @YES}],
        @kAudioAggregateDeviceTapAutoStartKey: @NO
    };
    status = AudioHardwareCreateAggregateDevice((__bridge CFDictionaryRef)configuration, &_aggregate);
    if (status) {
        [self stop];
        return problem(error, @"Create temporary audio relay", status);
    }
    if (!stream_format(_aggregate, kAudioObjectPropertyScopeInput, &inFormat) ||
        !stream_format(_aggregate, kAudioObjectPropertyScopeOutput, &outFormat) ||
        !equal_format(inFormat, outFormat) || !equal_format(inFormat, tapFormat)) {
        [self stop];
        return problem(error, @"Unsupported relay layout; media unchanged", 0);
    }
    atomic_init(&_state.fault, false);
    atomic_init(&_state.receivedMedia, false);
    _state.gain = gain;
    status = AudioDeviceCreateIOProcID(_aggregate, relay_audio, &_state, &_io);
    if (status) {
        [self stop];
        return problem(error, @"Prepare media relay", status);
    }
    // The only point at which media capture is started. macOS owns permission.
    status = AudioDeviceStart(_aggregate, _io);
    if (status) {
        [self stop];
        return problem(error, @"Start media relay; system-audio permission may be required", status);
    }
    _started = YES;
    return YES;
}

- (BOOL)healthy {
    return _started && !atomic_load_explicit(&_state.fault, memory_order_relaxed) && default_output() == _output;
}
- (BOOL)receivedMedia { return atomic_load_explicit(&_state.receivedMedia, memory_order_relaxed); }
- (void)stop {
    if (_started) { AudioDeviceStop(_aggregate, _io); _started = NO; }
    if (_io) { AudioDeviceDestroyIOProcID(_aggregate, _io); _io = NULL; }
    if (_aggregate) { AudioHardwareDestroyAggregateDevice(_aggregate); _aggregate = 0; }
    // MutedWhenTapped releases the original output when the tap stops being read.
    if (_tap) { AudioHardwareDestroyProcessTap(_tap); _tap = 0; }
}
- (void)dealloc { [self stop]; }
@end
