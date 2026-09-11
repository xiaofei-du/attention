#import <Foundation/Foundation.h>

// Temporary media relay on the default output. Requires system-audio permission.
@interface NKCDucker : NSObject
+ (NSDictionary *)outputInfo:(NSError **)error; // Read-only; no tap created.
- (BOOL)startWithGain:(float)gain error:(NSError **)error;
- (BOOL)healthy;
- (BOOL)receivedMedia;
- (void)stop;
@end
