# Custom Geek Bar Pulse X Jam Firmware
Because the lights are pretty and I wanted to be able to use 100% of the original electronics.

For full transparency, I used Claude Code pretty heavily to get all this to work. I know how to write arduino code, but I have ZERO idea how to deconstruct a binary or where to even being when hacking stuff. Claude did most of the heavy lifting in regards to scraping the dumped binary for animations, the SPI protocol, default pin assignments, etc. I was able to get most of the way there just by tracing the PCB and trial and error but I hit a brick wall when trying to program. So, I included my context file so others can use if they wish.

## What it does now
There's a glued-in button that goes where the mouthpiece used to be. Pressing it shows off some animations. There is a simple counter mode that you can use to, count things? Idk there's not much you can do with only one 3-position switch and a button :)

Maybe someone will implement a timer. There's not much else I can think of without heavily modifying the PCB. Could get funky with the "microphone" (what's a microphone if not a really shitty speaker in reverse)

### Switch
- **Position 1 "Close"**: Low-ish power mode. Pressing the button will show the selected animation. Holding the button lights up all the LEDs and shows the battery percentage on the top, and the "raw" voltage on the bottom number displays.
- **Position 2 "Animation Select"**: Cycle through the animations with the button.
- **Position 3 "Counter"**: Increase the counter with the button. Long press to reset the counter.

### Animations
There are 11 LED animations. I/Claude tried to copy a bunch of the original/stock animations from the dumped flash binary. Added a few new ones in there for flavor and fun.

## References
Huge shoutout to all the shoulders I've stood on to get this far. So much research here:

__https://www.reddit.com/r/streetlithium/__

__https://www.reddit.com/r/hardwarehacking/comments/1p0gh2c/geekbar_pulse_x_screen_reverse_engineered/__

__https://github.com/sm2013-vapehack/geekbar_pulse_x_screen_reuse__


https://github.com/py32duino/Arduino-PY32

https://www.instructables.com/PY32Duino-Anemometer-Aka-Making-a-Wind-Speed-Meter/

https://py32.org/en/mcu/PY32F030xx.html

https://github.com/TDLOGY/py32f0-template-project/

https://github.com/grahamwhaley/py32c642_vape

## Hardware Info

### Microcontroller (PY32F030EK28):

Datasheet: https://download.py32.org/Datasheet/en/PY32F030_Datasheet_V1.8.pdf

Reference Manual: https://download.py32.org/ReferenceManual/en/PY32F030%20Reference%20manual%20v1.3_EN.pdf

<img width="730" height="428" alt="image" src="https://github.com/user-attachments/assets/715689a6-78c7-44db-adfc-f8d8e290aa0e" />

  PA2:   Analog input for the mode selector switch
  PA9:   SCL
  PA12:  MOSI
  PA13:  SWDIO
  PA14:  SWCLK
  PA15:  LED Driver Enable (active low, PNP controlled)
  PB1:   Originally some sort of on/off control for one of the vape heating elements.
         Now I'm using it for a button that sits where the mouthpiece used to go.

  PF0:   USB Sense (?)
  PB5:   Charge indicator (?)
   ^ idk about these two, never bothered reverse engineering this completely. There are TWO charging ICs for some reason

  A few more pins are used for the microphone (sensing pressure/inhale), the power/heating element controls, etc. I didn't really bother with these.

### Programming the microcontroller
This took the longest to figure out. I fucked around with the boot pin, the pulldown resistors, tried to use UART, all to no avail. In the end, turns out Ockham's Razor is true in this case: the SWD pins (PA13/PA14) are brought out to the USB port! That makes sense. They probably wanted this thing to be as easy to produce as possible and it would suck really bad to re-program a batch if you had to open them up. They suck to open up.

Note that I did remove the 2.5k pulldowns on the board (or, I think they were 2.5k? Idk I removed and then promptly lost and forgot. Oops). I _think_ you don't need to do this. If you leave you'll need to adjust the pullup resistors on your pico or otherwise increase the drive strength or something.

I used a Raspberry Pi Pico as a SWD programmer. You can look up how to do this it's not too hard but can be tricky to get the software environment set up. I used __pyocd__. I soldered some series 240 ohm resistors, since the pico runs at 3.3V but the PUYA board runs at... whatever tf the battery voltage is so, like 5V if you plug in USB or up to 4.2 if you've got a fresh battery. Also soldered in 10k pullups.

A USB-C breakout like this one is useful to have here: https://www.amazon.com/dp/B0CD61X3FG

The pins they ended up using are the "5th" pins on a full USB-C pinout, or A5 and B5. Pico pins were as follows for me:

    SWCLK: GP2 -> 250ohm -> B5 ----> PA14
    SWDIO: GP3 -> 250ohm -> A5 ----> PA13
      ^ both pulled up to 3.3V with 10k

Try plugging it in and opening with PYOCD. If it doesn't work, flip the connector around lol the pins are symmetric
  
### Other Hardware Info
Slide selector switch part: 

  Product listing: https://www.lcsc.com/product-detail/C46597996.html?lcsc_vid=RQReA1EFRAJZVAZUQQQMVAUCRVVcU1VXFgBeXlZfRFAxVlNRTlVfUlNWT1BaVjtW
  
  Datasheet: https://www.lcsc.com/datasheet/C46597996.pdf?lcsc_vid=RQReA1EFRAJZVAZUQQQMVAUCRVVcU1VXFgBeXlZfRFAxVlNRTlVfUlNWT1BaVjtW

Charging IC (LP4068):

  Datasheet: https://taoic.oss-cn-hangzhou.aliyuncs.com/9224/product/13480837890_1633922467000.pdf

SPI to the display controller:

  On a scope the MOSI line was never hitting actual 3.3V levels. It was always capped at like 1.8V or something. Idk why, probably some hardware protection diodes internal to one of the chips? Either way, seemed to work just fine.
