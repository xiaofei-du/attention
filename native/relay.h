#pragma once
#include <CoreAudio/CoreAudioTypes.h>
#include <math.h>
#include <stdbool.h>
#include <string.h>

// Real-time path: no allocations, locks, file I/O, or logging. Only validated
// Float32 streams reach this function. Return false on any layout change.
static inline bool nkc_relay(const AudioBufferList *input, AudioBufferList *output, float gain) {
    if (!output) return false;
    for (UInt32 b = 0; b < output->mNumberBuffers; b++)
        if (output->mBuffers[b].mData)
            memset(output->mBuffers[b].mData, 0, output->mBuffers[b].mDataByteSize);
    if (!input || !isfinite(gain) || gain < 0 || gain > 1 ||
        !input->mNumberBuffers || input->mNumberBuffers != output->mNumberBuffers) return false;
    for (UInt32 b = 0; b < input->mNumberBuffers; b++) {
        const AudioBuffer *src = &input->mBuffers[b], *dst = &output->mBuffers[b];
        if (!src->mData || !dst->mData || !src->mNumberChannels ||
            src->mNumberChannels != dst->mNumberChannels ||
            src->mDataByteSize != dst->mDataByteSize ||
            src->mDataByteSize % (sizeof(float) * src->mNumberChannels)) return false;
    }
    for (UInt32 b = 0; b < input->mNumberBuffers; b++) {
        const float *src = input->mBuffers[b].mData;
        float *dst = output->mBuffers[b].mData;
        for (UInt32 s = 0; s < input->mBuffers[b].mDataByteSize / sizeof(float); s++)
            dst[s] = isfinite(src[s]) ? src[s] * gain : 0;
    }
    return true;
}
