// Drives the real lightning_bugs.ino: sync the unit mid-show, then have the host move the grid so that the
// unit is between shows, and report what the LED driver's power pin (PA15, LOW = powered) did while it waited.
#include <stdio.h>
#include <sys/mman.h>
#include "../../firmware/lightning_bugs/lightning_bugs.ino"

static const int64_t PERIOD_US = 3600LL * 1000000;
static int64_t nextStart;
static unsigned long waitSamples, poweredWhileWaiting;
static bool resyncDone, measuring;
static uint32_t seqNow = 0;

static void hostWriteSync(uint32_t anchorTick, int64_t anchorUs, int64_t epochUs) {   // as lb_sync.py write_sync()
    lbBlock.seq = seqNow + 1;
    lbBlock.anchor_tick = anchorTick;
    lbBlock.anchor_us_lo = (uint32_t)anchorUs; lbBlock.anchor_us_hi = (uint32_t)(anchorUs >> 32);
    lbBlock.corr_ppb = 0;
    lbBlock.epoch_us_lo = (uint32_t)epochUs; lbBlock.epoch_us_hi = (uint32_t)(epochUs >> 32);
    lbBlock.period_us = (uint32_t)PERIOD_US;
    seqNow += 2;
    lbBlock.seq = seqNow;
}

static void hook() {
    int64_t now = lbMasterUs();
    if (!resyncDone && now >= 1000LL * PERIOD_US + 2500000) {          // 2.5 s into the show
        resyncDone = true;
        hostWriteSync(uwTick, now, now - 60LL * 1000000);              // new grid: last beat was 60 s ago
    }
    if (measuring && now < nextStart - 500000) {                       // waiting for the next show
        waitSamples++;
        if (sim.level[PA15] == LOW) poweredWhileWaiting++;
    }
}

int main() {
    // The sketch reads the chip UID and temperature calibration from fixed flash addresses.
    void* p = mmap((void*)0x1FFF0000, 0x1000, PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANONYMOUS | MAP_FIXED_NOREPLACE, -1, 0);
    if (p == MAP_FAILED) { puts("mmap failed"); return 2; }
    *(volatile uint16_t*)LB_TSCAL1_ADDR = 1400; *(volatile uint16_t*)LB_TSCAL2_ADDR = 1700;

    setup();
    sim.onWfi = hook;
    hostWriteSync(uwTick, 1000LL * PERIOD_US + 1000000, 0);            // master time = beat 1000 + 1 s: mid-show
    loop();                                                            // starts the show; the hook resyncs it away
    printf("resynced=%d show_cut_short=%d\n", resyncDone, resyncDone);
    nextStart = lbBeatTime(lbBeatIndex(lbMasterUs()) + 1);
    measuring = true;
    loop();                                                            // waits out the hour, then plays a show
    printf("wait_samples=%lu powered_while_waiting=%lu\n", waitSamples, poweredWhileWaiting);
    return 0;
}
