// On-device language identification and installed voice metadata. No audio capture.
#import <Foundation/Foundation.h>
#import <NaturalLanguage/NaturalLanguage.h>
#import <AppKit/AppKit.h>

// AppKit exposes metadata for the exact voices used by /usr/bin/say. The newer
// AVSpeech catalog does not guarantee the same names. Keep this compatibility
// boundary isolated; never infer gender from a voice's name.
#pragma clang diagnostic push
#pragma clang diagnostic ignored "-Wdeprecated-declarations"
static NSArray *voiceCatalog(void) {
    NSMutableArray *voices = [NSMutableArray array];
    for (NSString *identifier in [NSSpeechSynthesizer availableVoices]) {
        NSDictionary *attributes = [NSSpeechSynthesizer attributesForVoice:identifier];
        NSString *name = attributes[NSVoiceName];
        NSString *locale = attributes[NSVoiceLocaleIdentifier];
        NSString *gender = attributes[NSVoiceGender];
        if (!name.length || !locale.length) continue;
        NSString *kind = [gender isEqualToString:NSVoiceGenderMale] ? @"male" :
                         [gender isEqualToString:NSVoiceGenderFemale] ? @"female" : @"unknown";
        [voices addObject:@{@"name": name, @"locale": locale, @"gender": kind}];
    }
    return voices;
}
#pragma clang diagnostic pop

int main(int argc, const char *argv[]) {
    @autoreleasepool {
        if (argc == 2 && strcmp(argv[1], "--voices") == 0) {
            NSData *result = [NSJSONSerialization dataWithJSONObject:voiceCatalog() options:0 error:NULL];
            [[NSFileHandle fileHandleWithStandardOutput] writeData:result];
            return 0;
        }
        if (argc != 1) return 2;
        NSData *data = [[NSFileHandle fileHandleWithStandardInput] readDataToEndOfFile];
        if (data.length > 65536) return 2;
        id items = [NSJSONSerialization JSONObjectWithData:data options:0 error:NULL];
        if (![items isKindOfClass:[NSArray class]]) return 2;
        NSMutableArray *languages = [NSMutableArray array];
        for (id item in items) {
            if (![item isKindOfClass:[NSString class]]) return 2;
            [languages addObject:[NLLanguageRecognizer dominantLanguageForString:item] ?: @"und"];
        }
        NSData *result = [NSJSONSerialization dataWithJSONObject:languages options:0 error:NULL];
        [[NSFileHandle fileHandleWithStandardOutput] writeData:result];
    }
    return 0;
}
