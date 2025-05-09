Weii
====

Weii (pronounced "weigh") is a small script that connects to a Wii Balance Board, reads a weight measurement, and disconnects.
Weii is the new, redesigned spiritual successor to [gr8w8upd8m8](https://github.com/skorokithakis/gr8w8upd8m8).

The latest version is available at https://github.com/skorokithakis/weii.

Installation
------------

To install using `pipx` (recommended) or `pip`, run:

```
pipx install weii
```

or

```
pip install weii
```


Usage
-----

Weii currently is only tested on Linux.
Before you use Weii, you need to pair your balance board via Bluetooth.
You can do that by pressing the red button in the battery compartment and then going through the normal Bluetooth pairing process.
I don't remember the pairing code, try 0000 or 1234, and please let me know which one is right.

To weigh yourself, run `weii` and follow the instructions.
You need to have paired your balance board beforehand, then press the button at the front of the board until the blue LED lights up solid, and step on.
Once the measurement is done, you can step off.

Weii can optionally use `bluetoothctl` to disconnect (and turn off) the balance board when the weighing is done, you can do that by passing the device's address to the `-d` argument:

```
weii --disconnect-when-done 11:22:33:44:55:66
```

You can run a command after weighing, like so:

```
weii --command "echo {weight}"
```

`{weight}` will be replaced with the measured weight.

You can also adjust the measurement to account for clothing, or to match some other scale:

```
weii --adjust=-2.3
```

License
-------

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU Affero General Public License as published
by the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU Affero General Public License for more details.

You should have received a copy of the GNU Affero General Public License
along with this program.  If not, see <https://www.gnu.org/licenses/>.
