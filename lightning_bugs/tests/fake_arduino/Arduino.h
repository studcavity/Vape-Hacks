// A just-enough Arduino/CMSIS stand-in to compile firmware/lightning_bugs/lightning_bugs.ino natively
// (g++, host CPU) and drive setup()/loop() under a simulated clock. Used only by tests/test_lightning_bugs_sketch.py.
// Time stands still except where the sketch sleeps: __WFI() and delay() advance uwTick (the HAL millisecond tick).
#pragma once
#include <stdint.h>
#include <stdbool.h>
#include <string.h>

extern "C" { inline volatile uint32_t uwTick = 0; }

#define INPUT 0
#define OUTPUT 1
#define INPUT_PULLUP 2
#define LOW 0
#define HIGH 1
#define CHANGE 1
#define RISING 2
#define FALLING 3
#define PA2 2
#define PA9 9
#define PA12 12
#define PA15 15
#define PF0 32
#define AVREF 100
#define ATEMP 101

struct GpioRegs { volatile uint32_t BSRR; };
struct PwrRegs { volatile uint32_t CR1; };
struct ScbRegs { volatile uint32_t SCR; };
inline GpioRegs gpioaRegs; inline PwrRegs pwrRegs; inline ScbRegs scbRegs;
#define GPIOA (&gpioaRegs)
#define PWR (&pwrRegs)
#define SCB (&scbRegs)
#define PWR_CR1_LPR (1u << 0)
#define SCB_SCR_SLEEPDEEP_Msk (1u << 2)

struct Sim {
    int level[64] = {};
    void (*onWfi)() = nullptr;              // called after every simulated 1 ms tick
    unsigned long wfiCalls = 0;
    unsigned long stopWfis = 0;             // WFIs entered with SLEEPDEEP set (STOP)
    uint32_t pa2Adc = 1500;                 // what analogRead(PA2) returns: <20 GND, >2000 VDDA, else mid-rail
};
inline Sim sim;

inline void tick() { uwTick = uwTick + 1; if (sim.onWfi) sim.onWfi(); }
inline void __WFI() { if (scbRegs.SCR & SCB_SCR_SLEEPDEEP_Msk) sim.stopWfis++; tick(); }
inline void __disable_irq() {}
inline void __enable_irq() {}
inline uint32_t millis() { return uwTick; }
inline void delay(uint32_t ms) { while (ms--) tick(); }
inline void delayMicroseconds(uint32_t) {}
inline void pinMode(int, int) {}
inline void digitalWrite(int pin, int v) { sim.level[pin] = v; }
inline int digitalRead(int pin) { return sim.level[pin]; }
inline int digitalPinToInterrupt(int pin) { return pin; }
inline void attachInterrupt(int, void (*)(), int) {}
inline void detachInterrupt(int) {}
inline void analogReadResolution(int) {}
inline uint32_t analogRead(uint32_t ch) { return ch == AVREF ? 1260 : ch == PA2 ? sim.pa2Adc : 1500; }   // VREFINT 1.2 V -> supply 3.9 V
