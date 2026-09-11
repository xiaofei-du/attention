#include "relay.h"
#include <assert.h>
#include <math.h>
#include <stdio.h>

int main(void) {
    float media[] = {0.8f, -0.4f, 0.2f, -1.0f};
    float out[] = {9, 9, 9, 9};
    AudioBufferList input = {1, {{2, sizeof(media), media}}};
    AudioBufferList output = {1, {{2, sizeof(out), out}}};
    assert(nkc_relay(&input, &output, 0.25f));
    for (int i = 0; i < 4; i++) assert(fabsf(out[i] - media[i] * 0.25f) < 0.000001f);
    assert(media[0] == 0.8f); // Source samples are never edited.

    // A route/buffer-size change must not copy beyond buffers or partly relay.
    input.mBuffers[0].mDataByteSize -= sizeof(float);
    assert(!nkc_relay(&input, &output, 0.25f));
    for (int i = 0; i < 4; i++) assert(out[i] == 0);
    input.mBuffers[0].mDataByteSize = sizeof(media);
    output.mBuffers[0].mNumberChannels = 1;
    assert(!nkc_relay(&input, &output, 0.25f));
    output.mBuffers[0].mNumberChannels = 2;
    assert(!nkc_relay(&input, &output, NAN));
    assert(!nkc_relay(&input, &output, 1.1f));
    assert(nkc_relay(&input, &output, 1.0f));
    for (int i = 0; i < 4; i++) assert(out[i] == media[i]);
    puts("gain, channel/size mismatch, invalid gain, and source preservation passed");
}
