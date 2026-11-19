// Drives the real lightning_bugs.ino with the slide switch at its off pole (PA2 at GND): the unit must enter STOP
// without a show, stay there while PA2 does not move, and come back when it does. Prints what happened.
#include <stdio.h>
#include <sys/mman.h>
#include "../../firmware/lightning_bugs/lightning_bugs.ino"

static void setSwitch(uint32_t adc, bool edge) {
    sim.pa2Adc = adc;
    sim.level[PA2] = adc < 20 ? LOW : HIGH;
    if (edge) onSwitchWake();                                          // what the PA2 EXTI would do
}

static bool released;
static void hook() {
    if (!released && sim.stopWfis >= 20000) { released = true; setSwitch(3000, true); }   // 20 s asleep, then moved
}

// "lowbatt-lost-edge": a latched low battery whose sleep is due; USB is plugged in while the sketch blanks the
// driver, i.e. after it decided to sleep and without the PF0 ISR running (the edge the old code lost).
// "lowbatt": same, but USB appears only after 20 s asleep, with its edge.
static bool lostEdge;
static void onWrite(int pin, int v) { if (lostEdge && pin == PA15 && v == HIGH) { sim.level[PF0] = HIGH; lostEdge = false; } }
static void usbHook() { if (!released && sim.stopWfis >= 20000) { released = true; sim.level[PF0] = HIGH; onUsbWake(); } }

int main(int argc, char** argv) {
    void* p = mmap((void*)0x1FFF0000, 0x1000, PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANONYMOUS | MAP_FIXED_NOREPLACE, -1, 0);
    if (p == MAP_FAILED) { puts("mmap failed"); return 2; }
    *(volatile uint16_t*)LB_TSCAL1_ADDR = 1400; *(volatile uint16_t*)LB_TSCAL2_ADDR = 1700;

    bool lowbatt = argc > 1 && argv[1][0] == 'l';
    bool off = argc > 1 && !lowbatt;                                               // any argument: start at the off pole
    setSwitch(off ? 5 : 1500, false);
    setup();
    sim.onWfi = lowbatt ? usbHook : hook;
    if (lowbatt) {
        lostEdge = !strcmp(argv[1], "lowbatt-lost-edge");
        sim.onWrite = onWrite;
        lbPower.latched = true; lbPower.window_end_ms = 0;             // sleep is due now
    }
    loop();                                                            // off: sleeps, then returns after the wake
    printf("stop_wfis=%lu released=%d synced=%d wakes=%u\n", sim.stopWfis, released, lbS.synced ? 1 : 0,
           (unsigned)lbBlock.wake_count);
    printf("led_power_pin=%d off_after=%d\n", sim.level[PA15], switchIsOff ? 1 : 0);
    return 0;
}
