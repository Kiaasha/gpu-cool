# GPU Cool

I render a lot on a laptop. Image and video generation can keep the GPU at 100% for hours, and on a laptop that means one thing: heat. My card sat at 77–80°C through every long render, the fans screamed, and the whole machine felt hot under my hands.

That temperature is technically "safe". The card won't throttle until much later. But I didn't want my laptop living there all day.

So I looked for the obvious fixes. The "Power saver" profile dropped performance way too hard. `nvidia-smi -gtt` (target temperature) is "not supported" on most laptop GPUs. The power limit can't be changed on them either. There was nothing in between "full speed and hot" and "slow and cool".

GPU Cool is that in-between. You pick a temperature, or a share of the card's power, and it quietly moves the GPU's clock cap up and down to stay there. On my card, holding 70°C costs a bit of speed and drops power from about 128 W to about 85–95 W.

## What it does

- Holds the GPU at a **target temperature** (60–85°C) or at a **% of the card's own power limit** (50–100%)
- Reads the card's max clock and power limit itself, so it works on any NVIDIA GPU, not just mine
- Live chart of temperature and clock for the last 5 minutes
- A small always-on-top readout that shifts a few pixels every minute, so it never burns into the screen
- Lives in the top bar next to the clock. Closing the window just hides it; **Quit** really exits
- Stop, Quit, or a reboot puts the GPU back to normal

It only lowers the clock cap. It never touches voltage, and the card's own thermal protections stay in place.

## Requirements

- Linux with the NVIDIA driver (`nvidia-smi`)
- Python 3 with Tk (`python3-tk`)
- A top bar that shows tray icons. On Ubuntu GNOME this is on by default (AppIndicator extension)
- The Python binding for tray icons:

```bash
sudo apt install python3-tk gir1.2-ayatanaappindicator3-0.1
```

## Install

```bash
git clone https://github.com/Kiaasha/gpu-cool.git ~/gpu-cool
```

Changing GPU clocks needs root. Instead of running a GUI as root, allow just these two `nvidia-smi` commands without a password:

```bash
echo "$USER ALL=(root) NOPASSWD: /usr/bin/nvidia-smi -lgc *, /usr/bin/nvidia-smi -rgc" | sudo tee /etc/sudoers.d/gpu-cool && sudo chmod 440 /etc/sudoers.d/gpu-cool && sudo visudo -c
```

Add it to your app menu:

```bash
sed "s|GPU_COOL_DIR|$HOME/gpu-cool|g" ~/gpu-cool/gpu-cool.desktop > ~/.local/share/applications/gpu-cool.desktop
```

## Use

Open **GPU Cool** from the app menu, pick Temperature or Power, set the slider, press **Start**. The mode is locked while it runs; press **Stop** to switch.

Opening it again while it's running just brings the window back.

## Uninstall

```bash
sudo rm /etc/sudoers.d/gpu-cool && rm ~/.local/share/applications/gpu-cool.desktop ~/.config/gpu_cool.json
```

## Tested on

Dell Precision 7760 with an RTX A5000 Laptop GPU, Ubuntu (GNOME, Wayland).
