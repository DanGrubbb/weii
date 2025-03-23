#!/usr/bin/env python3
# Copyright (C) 2023  Stavros Korokithakis
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published
# by the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

import argparse
import re
import statistics
import subprocess
import sys
import time
import threading
from typing import List
from typing import Optional

import evdev
from evdev import ecodes
import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk, GLib, Gio, Gdk, Adw

# Global variables
TERSE = False
measuring = False
current_weight = 0.0
status_message = "Waiting for balance board..."
device_found = False

class WiiBoardWindow(Gtk.ApplicationWindow):
    def __init__(self, app, *args, **kwargs):
        super().__init__(application=app, *args, **kwargs)
        
        # Set up the window
        self.set_title("Wii Balance Board")
        self.set_default_size(400, 300)
        
        # Create header bar
        header = Gtk.HeaderBar()
        self.set_titlebar(header)
        
        # Settings button
        menu_button = Gtk.MenuButton()
        menu_button.set_icon_name("open-menu-symbolic")
        header.pack_end(menu_button)
        
        # Settings menu
        builder = Gtk.Builder.new_from_string("""
        <?xml version="1.0" encoding="UTF-8"?>
        <interface>
          <menu id="menu">
            <section>
              <item>
                <attribute name="label">About</attribute>
                <attribute name="action">app.about</attribute>
              </item>
            </section>
          </menu>
        </interface>
        """, -1)
        
        menu = builder.get_object("menu")
        menu_model = Gio.MenuModel.new_from_model(menu)
        menu_button.set_menu_model(menu_model)
        
        # Create main box
        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        main_box.set_margin_top(20)
        main_box.set_margin_bottom(20)
        main_box.set_margin_start(20)
        main_box.set_margin_end(20)
        self.set_child(main_box)
        
        # Status label
        self.status_label = Gtk.Label(label=status_message)
        self.status_label.set_wrap(True)
        self.status_label.set_width_chars(40)
        main_box.append(self.status_label)
        
        # Weight display
        weight_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        weight_box.set_halign(Gtk.Align.CENTER)
        
        self.weight_label = Gtk.Label(label="0.0")
        self.weight_label.add_css_class("weight-value")
        self.weight_label.set_markup("<span font_desc='40'>0.0</span>")
        weight_box.append(self.weight_label)
        
        kg_label = Gtk.Label(label="kg")
        kg_label.add_css_class("weight-unit")
        kg_label.set_markup("<span font_desc='20'>kg</span>")
        kg_label.set_valign(Gtk.Align.END)
        kg_label.set_margin_bottom(10)
        weight_box.append(kg_label)
        
        main_box.append(weight_box)
        
        # Settings
        settings_frame = Gtk.Frame(label="Settings")
        settings_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        settings_box.set_margin_top(10)
        settings_box.set_margin_bottom(10)
        settings_box.set_margin_start(10)
        settings_box.set_margin_end(10)
        settings_frame.set_child(settings_box)
        main_box.append(settings_frame)
        
        # Adjustment setting
        adj_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        adj_label = Gtk.Label(label="Weight adjustment:")
        adj_label.set_halign(Gtk.Align.START)
        adj_label.set_hexpand(True)
        adj_box.append(adj_label)
        
        adj_adjustment = Gtk.Adjustment(value=0, lower=-20, upper=20, step_increment=0.1)
        self.adj_spin = Gtk.SpinButton(adjustment=adj_adjustment, climb_rate=0.1, digits=1)
        adj_box.append(self.adj_spin)
        settings_box.append(adj_box)
        
        # Minimum weight limit setting
        min_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        min_label = Gtk.Label(label="Minimum weight limit (kg):")
        min_label.set_halign(Gtk.Align.START)
        min_label.set_hexpand(True)
        min_box.append(min_label)
        
        min_adjustment = Gtk.Adjustment(value=20, lower=1, upper=50, step_increment=1)
        self.min_spin = Gtk.SpinButton(adjustment=min_adjustment, climb_rate=1, digits=0)
        min_box.append(self.min_spin)
        settings_box.append(min_box)
        
        # Disconnect address setting
        disconnect_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        disconnect_label = Gtk.Label(label="Disconnect address:")
        disconnect_label.set_halign(Gtk.Align.START)
        disconnect_label.set_hexpand(True)
        disconnect_box.append(disconnect_label)
        
        self.disconnect_entry = Gtk.Entry()
        self.disconnect_entry.set_placeholder_text("AA:BB:CC:DD:EE:FF")
        disconnect_box.append(self.disconnect_entry)
        settings_box.append(disconnect_box)
        
        # Command setting
        cmd_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        cmd_label = Gtk.Label(label="Command:")
        cmd_label.set_halign(Gtk.Align.START)
        cmd_label.set_hexpand(True)
        cmd_box.append(cmd_label)
        
        self.cmd_entry = Gtk.Entry()
        self.cmd_entry.set_placeholder_text("Command to run (use {weight} for value)")
        cmd_box.append(self.cmd_entry)
        settings_box.append(cmd_box)
        
        # Action buttons
        button_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        button_box.set_halign(Gtk.Align.CENTER)
        button_box.set_margin_top(10)
        
        self.measure_button = Gtk.Button(label="Start Measuring")
        self.measure_button.connect("clicked", self.on_measure_clicked)
        button_box.append(self.measure_button)
        
        main_box.append(button_box)
        
        # Start status update timer
        GLib.timeout_add(500, self.update_status)
        
    def on_measure_clicked(self, button):
        global measuring
        
        if not measuring:
            # Start measurement in a separate thread
            adjust = self.adj_spin.get_value()
            minlimit = self.min_spin.get_value()
            disconnect_address = self.disconnect_entry.get_text()
            command = self.cmd_entry.get_text() if self.cmd_entry.get_text() else None
            
            self.measure_button.set_label("Cancel")
            measuring = True
            
            threading.Thread(
                target=self.measure_thread, 
                args=(adjust, minlimit, disconnect_address, command),
                daemon=True
            ).start()
        else:
            # Cancel measurement
            measuring = False
            self.measure_button.set_label("Start Measuring")
    
    def measure_thread(self, adjust, minlimit, disconnect_address, command):
        global measuring, current_weight, status_message, device_found
        
        try:
            # Perform the measurement
            status_message = "Waiting for balance board..."
            device_found = False
            
            # Wait for the board
            board = None
            while measuring and not board:
                board = get_board_device()
                if board:
                    status_message = "Balance board found, please step on."
                    device_found = True
                    break
                time.sleep(0.5)
            
            if not measuring:
                return
                
            # Read the weight data
            weight_data = read_data(board, 200, threshold=minlimit)
            
            if weight_data and measuring:
                final_weight = statistics.median(weight_data)
                final_weight += adjust
                current_weight = final_weight
                status_message = f"Done, weight: {final_weight:.1f} kg"
                
                # Disconnect if requested
                if disconnect_address:
                    status_message += "\nDisconnecting..."
                    subprocess.run(
                        ["/usr/bin/env", "bluetoothctl", "disconnect", disconnect_address],
                        capture_output=True,
                    )
                
                # Run command if specified
                if command:
                    subprocess.run(command.replace("{weight}", f"{final_weight:.1f}"), shell=True)
            
        except Exception as e:
            status_message = f"Error: {str(e)}"
        
        finally:
            GLib.idle_add(self.finish_measurement)
    
    def finish_measurement(self):
        global measuring
        measuring = False
        self.measure_button.set_label("Start Measuring")
        return False
    
    def update_status(self):
        # Update UI elements based on global state
        self.status_label.set_text(status_message)
        self.weight_label.set_markup(f"<span font_desc='40'>{current_weight:.1f}</span>")
        
        # Enable/disable controls based on measuring state
        self.adj_spin.set_sensitive(not measuring)
        self.min_spin.set_sensitive(not measuring)
        self.disconnect_entry.set_sensitive(not measuring)
        self.cmd_entry.set_sensitive(not measuring)
        
        return True  # Continue the timer

class WiiBoardApp(Adw.Application):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.connect('activate', self.on_activate)
        
    def on_activate(self, app):
        self.win = WiiBoardWindow(self)
        self.win.present()
        
        # Add actions
        action = Gio.SimpleAction.new("about", None)
        action.connect("activate", self.on_about)
        self.add_action(action)
    
    def on_about(self, action, param):
        about = Gtk.AboutDialog()
        about.set_transient_for(self.win)
        about.set_modal(True)
        about.set_program_name("Wii Balance Board")
        about.set_version("1.0")
        about.set_copyright("Copyright © 2023 Stavros Korokithakis")
        about.set_authors(["Stavros Korokithakis"])
        about.set_comments("Measure weight using a Wii Balance Board")
        about.set_license_type(Gtk.License.AGPL_3_0)
        about.present()

# Original functions from the CLI script
def debug(message: str, force: bool = False) -> None:
    if force or not TERSE:
        print(message)

def get_board_device() -> Optional[evdev.InputDevice]:
    """Return the Wii Balance Board device."""
    devices = [
        path
        for path in evdev.list_devices()
        if evdev.InputDevice(path).name == "Nintendo Wii Remote Balance Board"
    ]
    if not devices:
        return None
    board = evdev.InputDevice(
        devices[0],
    )
    return board

def get_raw_measurement(device: evdev.InputDevice) -> float:
    """Read one measurement from the board."""
    data = [None] * 4
    while True:
        event = device.read_one()
        if event is None:
            continue
        # Measurements are in decigrams, so we convert them to kilograms here.
        if event.code == ecodes.ABS_HAT1X:
            # Top left.
            data[0] = event.value / 100
        elif event.code == ecodes.ABS_HAT0X:
            # Top right.
            data[1] = event.value / 100
        elif event.code == ecodes.ABS_HAT0Y:
            # Bottom left.
            data[2] = event.value / 100
        elif event.code == ecodes.ABS_HAT1Y:
            # Bottom right.
            data[3] = event.value / 100
        elif event.code == ecodes.BTN_A:
            sys.exit("ERROR: User pressed board button while measuring, aborting.")
        elif event.code == ecodes.SYN_DROPPED:
            pass
        # Fixed the syntax errors where == was missing
        elif event.code == ecodes.SYN_REPORT and event.value == 3:
            pass
        elif event.code == ecodes.SYN_REPORT and event.value == 0:
            if None in data:
                # This measurement failed to read one of the sensors, try again.
                data = [None] * 4
                continue
            else:
                return sum(data)  # type: ignore
        else:
            debug(f"ERROR: Got unexpected event: {evdev.categorize(event)}")

def read_data(device: evdev.InputDevice, samples: int, threshold: float) -> List[float]:
    """
    Read weight data from the board.
    samples - The number of samples we ideally want to collect, if the user doesn't
              cancel.
    threshold - The weight (in kilos) to cross before starting to consider measurements
                valid.
    """
    global measuring, status_message
    
    data: List[float] = []
    while measuring:
        measurement = get_raw_measurement(device)
        if len(data) and measurement < threshold:
            # The user stepped off the board.
            status_message = "User stepped off."
            break
        if len(data) == 0 and measurement < threshold:
            # This measurement is too light and measurement hasn't yet started, ignore.
            continue
        data.append(measurement)
        if len(data) == 1:
            status_message = "Measurement started, please wait..."
        if len(data) >= samples:
            # We have enough samples now.
            break
        
        # Update status with current count
        if len(data) % 10 == 0:
            status_message = f"Measuring... {len(data)}/{samples} samples"
            
    device.close()
    return data

def measure_weight(
    adjust: float,
    minlimit: float,
    disconnect_address: str,
    command: Optional[str],
    terse: bool,
    fake: bool = False,
) -> float:
    """Perform one weight measurement."""
    global status_message
    
    if disconnect_address and not re.match(
        r"^([0-9a-f]{2}[:]){5}([0-9a-f]{2})$", disconnect_address, re.IGNORECASE
    ):
        sys.exit("ERROR: Invalid device address to disconnect specified.")
        
    status_message = "Waiting for balance board..."
    while not fake:
        board = get_board_device()
        if board:
            break
        time.sleep(0.5)
    status_message = "Balance board found, please step on."
    
    if fake:
        weight_data = [85.2] * 200
    else:
        weight_data = read_data(board, 200, threshold=minlimit)
        
    final_weight = statistics.median(weight_data)
    final_weight += adjust
    
    if terse:
        debug(f"{final_weight:.1f}", force=True)
    else:
        status_message = f"Done, weight: {final_weight:.1f}."
        
    if disconnect_address:
        status_message += "\nDisconnecting..."
        subprocess.run(
            ["/usr/bin/env", "bluetoothctl", "disconnect", disconnect_address],
            capture_output=True,
        )
        
    if command:
        subprocess.run(command.replace("{weight}", f"{final_weight:.1f}"), shell=True)
        
    return final_weight

def main():
    # Set up CSS provider for styling
    css_provider = Gtk.CssProvider()
    css_provider.load_from_data("""
    .weight-value {
        font-weight: bold;
    }
    """.encode())
    
    Gtk.StyleContext.add_provider_for_display(
        Gdk.Display.get_default(),
        css_provider,
        Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
    )
    
    app = WiiBoardApp(application_id="com.example.wiiboard")
    return app.run(sys.argv)

if __name__ == "__main__":
    main()