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
import cairo
import json
import os
import math
from pathlib import Path
from typing import List
from typing import Optional

import evdev
from evdev import ecodes
import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, GLib, Gio, Gdk, Adw

# Global variables
TERSE = False
measuring = False
current_weight = 0.0
current_bmi = 0.0
status_message = "Ready"
device_found = False
CONFIG_FILE = os.path.join(os.path.expanduser("~/.config/weii/"), "weii.conf")
DEFAULT_MIN_WEIGHT_LIMIT = 20  # Default minimum weight limit in kg

# BMI category ranges
BMI_CATEGORIES = {
    "Underweight": (0, 18.5),
    "Normal weight": (18.5, 25),
    "Overweight": (25, 30),
    "Obese": (30, 100),
}

# BMI colors
BMI_COLORS = {
    "Underweight": (0.95, 0.9, 0.25),  # Yellow
    "Normal weight": (0.25, 0.8, 0.25),  # Green
    "Overweight": (0.95, 0.5, 0.2),  # Orange
    "Obese": (0.9, 0.2, 0.2),  # Red
}

class BMIScaleDrawingArea(Gtk.DrawingArea):
    def __init__(self):
        super().__init__()

        self.bmi = 0
        self.set_content_width(400)
        self.set_content_height(80)
        
        # Create a style context for getting colors
        self.style_context = self.get_style_context()
        
        # Set up the drawing function
        self.set_draw_func(self._draw_func, None)  # Pass None as user_data
        
    def set_bmi(self, bmi):
        self.bmi = bmi
        self.queue_draw()
        
    def _draw_func(self, area, cr, width, height, user_data):
        # No background - transparent
        cr.save()
        cr.set_operator(cairo.OPERATOR_CLEAR)
        cr.paint()
        cr.restore()
        
        # Draw BMI scale
        margin = 10
        bar_height = 15  # Slimmer bar
        bar_y = height / 2 - bar_height / 2
        bar_width = width - 2 * margin
        corner_radius = 7  # Rounded corners
        
        # Calculate positions
        bmi_min, bmi_max = 10, 40  # Range of BMI to display
        scale_factor = bar_width / (bmi_max - bmi_min)
        
        # Set text color (using a fixed dark color instead of system color)
        text_color_rgb = (0.1, 0.1, 0.1)  # Dark gray
        
        # Draw colored segments
        segments = []
        for category, (min_val, max_val) in sorted(BMI_CATEGORIES.items(), key=lambda x: x[1][0]):
            # Clamp values to our display range
            display_min = max(min_val, bmi_min)
            display_max = min(max_val, bmi_max)
            
            if display_max <= display_min:
                continue
                
            start_x = margin + (display_min - bmi_min) * scale_factor
            end_x = margin + (display_max - bmi_min) * scale_factor
            segment_width = end_x - start_x
            
            segments.append((category, start_x, end_x, segment_width))
        
        # Draw each segment with proper rounding
        for i, (category, start_x, end_x, segment_width) in enumerate(segments):
            is_first = i == 0
            is_last = i == len(segments) - 1
            
            cr.new_path()
            
            if is_first and is_last:
                # Single segment with both corners rounded
                cr.arc(start_x + corner_radius, bar_y + corner_radius, corner_radius, math.pi, 1.5 * math.pi)
                cr.arc(end_x - corner_radius, bar_y + corner_radius, corner_radius, 1.5 * math.pi, 2 * math.pi)
                cr.arc(end_x - corner_radius, bar_y + bar_height - corner_radius, corner_radius, 0, 0.5 * math.pi)
                cr.arc(start_x + corner_radius, bar_y + bar_height - corner_radius, corner_radius, 0.5 * math.pi, math.pi)
            elif is_first:
                # First segment (left side rounded)
                cr.arc(start_x + corner_radius, bar_y + corner_radius, corner_radius, math.pi, 1.5 * math.pi)
                cr.line_to(end_x, bar_y)
                cr.line_to(end_x, bar_y + bar_height)
                cr.arc(start_x + corner_radius, bar_y + bar_height - corner_radius, corner_radius, 0.5 * math.pi, math.pi)
            elif is_last:
                # Last segment (right side rounded)
                cr.move_to(start_x, bar_y)
                cr.line_to(end_x - corner_radius, bar_y)
                cr.arc(end_x - corner_radius, bar_y + corner_radius, corner_radius, 1.5 * math.pi, 2 * math.pi)
                cr.arc(end_x - corner_radius, bar_y + bar_height - corner_radius, corner_radius, 0, 0.5 * math.pi)
                cr.line_to(start_x, bar_y + bar_height)
            else:
                # Middle segment (no rounded corners)
                cr.rectangle(start_x, bar_y, segment_width, bar_height)
            
            cr.close_path()
            
            r, g, b = BMI_COLORS[category]
            cr.set_source_rgb(r, g, b)
            cr.fill()
            
            # Add category labels
            cr.set_source_rgb(*text_color_rgb)
            cr.select_font_face("Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_NORMAL)
            cr.set_font_size(10)
            
            # Center text in segment
            text_x = start_x + segment_width / 2
            text_y = bar_y + bar_height + 15
            
            text = category
            text_extents = cr.text_extents(text)
            cr.move_to(text_x - text_extents.width/2, text_y)
            cr.show_text(text)
            
            # Add numeric values for ends of scale
            if is_first:
                cr.set_font_size(8)
                cr.move_to(start_x, bar_y - 5)
                cr.show_text(f"{bmi_min}")
            
            if is_last:
                cr.set_font_size(8)
                cr.move_to(end_x - 10, bar_y - 5)
                cr.show_text(f"{bmi_max}")
        
        # Draw marker for current BMI if valid
        if self.bmi > 0:
            marker_x = margin + (min(max(self.bmi, bmi_min), bmi_max) - bmi_min) * scale_factor
            
            # Use consistent text color
            cr.set_source_rgb(*text_color_rgb)
            
            # Draw triangle marker
            cr.move_to(marker_x, bar_y - 10)
            cr.line_to(marker_x - 6, bar_y - 20)
            cr.line_to(marker_x + 6, bar_y - 20)
            cr.close_path()
            cr.fill()
            
            # Draw BMI value above marker
            cr.select_font_face("Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
            cr.set_font_size(12)
            
            bmi_text = f"{self.bmi:.1f}"
            text_extents = cr.text_extents(text)
            cr.move_to(marker_x - text_extents.width/2, bar_y - 25)
            cr.show_text(bmi_text)

class Config:
    """Class to handle configuration loading and saving"""
    def __init__(self, config_file):
        self.config_file = config_file
        self.config = self.load_config()
        
    def load_config(self):
        """Load configuration from file or return defaults"""
        try:
            if os.path.exists(self.config_file):
                with open(self.config_file, 'r') as f:
                    return json.load(f)
        except Exception as e:
            print(f"Error loading config: {e}")
            
        # Default configuration
        return {
            "use_imperial": False,
            "height_cm": 170,
            "height_feet": 5,
            "height_inches": 7,
            "weight_adjust": 0,
            "gender": "male"
        }
        
    def save_config(self, config_data):
        """Save configuration to file"""
        try:
            self.config = config_data
            with open(self.config_file, 'w') as f:
                json.dump(self.config, f, indent=2)
            return True
        except Exception as e:
            print(f"Error saving config: {e}")
            return False

class WiiBoardWindow(Gtk.ApplicationWindow):
    def __init__(self, app, *args, **kwargs):
        super().__init__(application=app, *args, **kwargs)
        
        # Load configuration
        self.config = Config(CONFIG_FILE)
        
        # Set up the window
        self.set_title("Weii")
        self.set_default_size(480, 550)  # Adjust for removed control
        
        # Default to saved config
        self.use_imperial = self.config.config["use_imperial"]
        
        # Create header bar
        header = Gtk.HeaderBar()
        self.set_titlebar(header)
        
        # Settings button
        menu_button = Gtk.MenuButton()
        menu_button.set_icon_name("open-menu-symbolic")
        header.pack_end(menu_button)
        
        # Settings menu
        menu_model = Gio.Menu()
        section = Gio.Menu()
        section.append("About", "app.about")
        menu_model.append_section(None, section)
        menu_button.set_menu_model(menu_model)
        
        # Create main box
        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=15)
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
        
        self.weight_unit_label = Gtk.Label(label="kg")
        self.weight_unit_label.add_css_class("weight-unit")
        self.weight_unit_label.set_markup("<span font_desc='20'>kg</span>")
        self.weight_unit_label.set_valign(Gtk.Align.END)
        self.weight_unit_label.set_margin_bottom(10)
        weight_box.append(self.weight_unit_label)
        
        main_box.append(weight_box)
        
        # BMI display
        bmi_frame = Gtk.Frame()
        bmi_frame.set_label("Body Mass Index (BMI)")
        bmi_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        bmi_box.set_margin_top(15)
        bmi_box.set_margin_bottom(15)
        bmi_box.set_margin_start(15)
        bmi_box.set_margin_end(15)
        bmi_frame.set_child(bmi_box)
        
        # BMI value
        bmi_value_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        bmi_value_box.set_halign(Gtk.Align.CENTER)
        
        self.bmi_label = Gtk.Label(label="0.0")
        self.bmi_label.set_markup("<span font_desc='24'>0.0</span>")
        bmi_value_box.append(self.bmi_label)
        
        self.bmi_category = Gtk.Label(label="")
        self.bmi_category.set_markup("<span font_desc='16'></span>")
        self.bmi_category.set_margin_start(10)
        bmi_value_box.append(self.bmi_category)
        
        bmi_box.append(bmi_value_box)
        
        # BMI scale
        self.bmi_scale = BMIScaleDrawingArea()
        bmi_box.append(self.bmi_scale)
        
        main_box.append(bmi_frame)
        
        # Settings
        settings_frame = Gtk.Frame()
        settings_frame.set_label("Settings")
        settings_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        settings_box.set_margin_top(15)
        settings_box.set_margin_bottom(15)
        settings_box.set_margin_start(15)
        settings_box.set_margin_end(15)
        settings_frame.set_child(settings_box)
        main_box.append(settings_frame)

        # Units selection
        units_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        units_label = Gtk.Label(label="Units:")
        units_label.set_halign(Gtk.Align.START)
        units_label.set_hexpand(True)
        units_box.append(units_label)
        
        self.metric_button = Gtk.ToggleButton(label="Metric")
        self.metric_button.set_active(not self.use_imperial)
        self.metric_button.connect("toggled", self.on_unit_toggled)
        
        self.imperial_button = Gtk.ToggleButton(label="Imperial")
        self.imperial_button.set_active(self.use_imperial)
        self.imperial_button.connect("toggled", self.on_unit_toggled)
        
        # Group the buttons
        units_group = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        units_group.add_css_class("linked")  # Make them appear as a segmented control
        units_group.append(self.metric_button)
        units_group.append(self.imperial_button)
        
        units_box.append(units_group)
        settings_box.append(units_box)
        
        # Height setting
        height_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        self.height_label = Gtk.Label(label="Height (cm):")
        self.height_label.set_halign(Gtk.Align.START)
        self.height_label.set_hexpand(True)
        height_box.append(self.height_label)
        
        # Metric height (cm)
        height_adjustment = Gtk.Adjustment(
            value=self.config.config["height_cm"], 
            lower=100, 
            upper=250, 
            step_increment=1
        )
        self.height_spin = Gtk.SpinButton(adjustment=height_adjustment, climb_rate=1, digits=0)
        self.height_spin.connect("value-changed", self.on_settings_changed)
        height_box.append(self.height_spin)
        
        # Imperial height (feet and inches)
        feet_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=5)
        
        feet_adjustment = Gtk.Adjustment(
            value=self.config.config["height_feet"], 
            lower=1, 
            upper=8, 
            step_increment=1
        )
        self.feet_spin = Gtk.SpinButton(adjustment=feet_adjustment, climb_rate=1, digits=0)
        self.feet_spin.connect("value-changed", self.on_settings_changed)
        feet_box.append(self.feet_spin)
        
        ft_label = Gtk.Label(label="ft")
        feet_box.append(ft_label)
        
        inches_adjustment = Gtk.Adjustment(
            value=self.config.config["height_inches"],
            lower=0, 
            upper=11, 
            step_increment=1
        )
        self.inches_spin = Gtk.SpinButton(adjustment=inches_adjustment, climb_rate=1, digits=0)
        self.inches_spin.connect("value-changed", self.on_settings_changed)
        feet_box.append(self.inches_spin)
        
        in_label = Gtk.Label(label="in")
        feet_box.append(in_label)
        
        height_box.append(feet_box)
        feet_box.set_visible(self.use_imperial)
        self.height_spin.set_visible(not self.use_imperial)
        
        settings_box.append(height_box)
        
        # Gender setting
        gender_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        gender_label = Gtk.Label(label="Gender:")
        gender_label.set_halign(Gtk.Align.START)
        gender_label.set_hexpand(True)
        gender_box.append(gender_label)
        
        # Fix for deprecated ComboBoxText methods
        self.gender_dropdown = Gtk.DropDown.new_from_strings(["Male", "Female"])
        self.gender_dropdown.set_selected(0 if self.config.config["gender"] == "male" else 1)
        self.gender_dropdown.connect("notify::selected", self.on_settings_changed)
        gender_box.append(self.gender_dropdown)
        settings_box.append(gender_box)
        
        # Adjustment setting
        adj_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        self.adj_label = Gtk.Label(label="Weight adjustment (kg):" if not self.use_imperial else "Weight adjustment (lb):")
        self.adj_label.set_halign(Gtk.Align.START)
        self.adj_label.set_hexpand(True)
        adj_box.append(self.adj_label)
        
        adj_adjustment = Gtk.Adjustment(
            value=self.config.config["weight_adjust"], 
            lower=-20, 
            upper=20, 
            step_increment=0.1
        )
        self.adj_spin = Gtk.SpinButton(adjustment=adj_adjustment, climb_rate=0.1, digits=1)
        self.adj_spin.connect("value-changed", self.on_settings_changed)
        adj_box.append(self.adj_spin)
        settings_box.append(adj_box)
        
        # Action buttons
        button_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        button_box.set_halign(Gtk.Align.CENTER)
        button_box.set_margin_top(15)
        
        self.measure_button = Gtk.Button(label="Start Measuring")
        self.measure_button.add_css_class("suggested-action")  # Give it a highlighted appearance
        self.measure_button.connect("clicked", self.on_measure_clicked)
        button_box.append(self.measure_button)
        
        main_box.append(button_box)
        
        # Start status update timer
        GLib.timeout_add(500, self.update_status)
        
    def on_settings_changed(self, widget, *args):
        """Save settings when they change"""
        self.save_current_config()
    
    def save_current_config(self):
        """Save current UI state to config"""
        config_data = {
            "use_imperial": self.use_imperial,
            "height_cm": self.height_spin.get_value(),
            "height_feet": self.feet_spin.get_value(),
            "height_inches": self.inches_spin.get_value(),
            "weight_adjust": self.adj_spin.get_value(),
            "gender": "male" if self.gender_dropdown.get_selected() == 0 else "female"
        }
        self.config.save_config(config_data)
    
    def on_unit_toggled(self, button):
        """Handle unit selection toggle"""
        if button == self.metric_button and button.get_active():
            self.imperial_button.set_active(False)
            self.use_imperial = False
            
            # Update UI for metric
            self.height_spin.set_visible(True)
            self.feet_spin.get_parent().set_visible(False)
            self.height_label.set_text("Height (cm):")
            self.adj_label.set_text("Weight adjustment (kg):")
            self.weight_unit_label.set_markup("<span font_desc='20'>kg</span>")
            
            # Convert any existing height from imperial to metric
            feet = self.feet_spin.get_value()
            inches = self.inches_spin.get_value()
            cm = int((feet * 12 + inches) * 2.54)
            self.height_spin.set_value(cm)
            
        elif button == self.imperial_button and button.get_active():
            self.metric_button.set_active(False)
            self.use_imperial = True
            
            # Update UI for imperial
            self.height_spin.set_visible(False)
            self.feet_spin.get_parent().set_visible(True)
            self.height_label.set_text("Height:")
            self.adj_label.set_text("Weight adjustment (lb):")
            self.weight_unit_label.set_markup("<span font_desc='20'>lb</span>")
            
            # Convert any existing height from metric to imperial
            cm = self.height_spin.get_value()
            total_inches = cm / 2.54
            feet = int(total_inches // 12)
            inches = round(total_inches % 12)
            
            # Handle case where inches becomes 12 after rounding
            if inches == 12:
                feet += 1
                inches = 0
                
            self.feet_spin.set_value(feet)
            self.inches_spin.set_value(inches)
        
        # Save changes to config
        self.save_current_config()
            
        # Update the display to reflect unit change
        self.update_weight_display()

    def update_weight_display(self):
        """Update weight display based on current unit system"""
        if current_weight > 0:
            if self.use_imperial:
                # Convert kg to lb
                weight_lb = current_weight * 2.20462
                self.weight_label.set_markup(f"<span font_desc='40'>{weight_lb:.1f}</span>")
            else:
                self.weight_label.set_markup(f"<span font_desc='40'>{current_weight:.1f}</span>")
    
    def get_height_in_cm(self):
        """Get height in cm regardless of current unit setting"""
        if self.use_imperial:
            feet = self.feet_spin.get_value()
            inches = self.inches_spin.get_value()
            return (feet * 12 + inches) * 2.54
        else:
            return self.height_spin.get_value()
    
    def get_adjustment_in_kg(self):
        """Get weight adjustment in kg regardless of current unit setting"""
        adjustment = self.adj_spin.get_value()
        if self.use_imperial:
            # Convert lb to kg
            return adjustment / 2.20462
        else:
            return adjustment
            
    def calculate_bmi(self, weight_kg, height_cm):
        """Calculate BMI from weight in kg and height in cm"""
        height_m = height_cm / 100.0
        bmi = weight_kg / (height_m * height_m)
        
        # Determine BMI category
        category = "Unknown"
        for cat, (min_val, max_val) in BMI_CATEGORIES.items():
            if min_val <= bmi < max_val:
                category = cat
                break
        
        return bmi, category
        
    def on_measure_clicked(self, button):
        global measuring, status_message
        
        if not measuring:
            # Start measurement in a separate thread
            adjust = self.get_adjustment_in_kg()
            minlimit = DEFAULT_MIN_WEIGHT_LIMIT  # Use the default value
            
            self.measure_button.set_label("Cancel")
            measuring = True
            status_message = "Waiting for balance board..."
            
            threading.Thread(
                target=self.measure_thread, 
                args=(adjust, minlimit),
                daemon=True
            ).start()
        else:
            # Cancel measurement
            measuring = False
            status_message = "Ready"
            self.measure_button.set_label("Start Measuring")
    
    def measure_thread(self, adjust, minlimit):
        global measuring, current_weight, current_bmi, status_message, device_found
        
        try:
            # Perform the measurement
            device_found = False
            
            # Wait for the board
            board = None
            while measuring and not board:
                board = get_board_device()
                if board:
                    status_message = "Please step on board"
                    device_found = True
                    break
                time.sleep(0.5)
            
            if not measuring:
                status_message = "Ready"
                return
                
            # Read the weight data
            weight_data = read_data(board, 200, threshold=minlimit)
            
            if weight_data and measuring:
                final_weight = statistics.median(weight_data)
                final_weight += adjust
                current_weight = final_weight
                
                # Calculate BMI
                height = self.get_height_in_cm()
                bmi, category = self.calculate_bmi(final_weight, height)
                current_bmi = bmi
                
                # Set simple status
                status_message = "Done"
            
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
        
        # Update weight display based on unit system
        self.update_weight_display()
        
        # Update BMI if we have a weight
        if current_weight > 0:
            height = self.get_height_in_cm()
            bmi, category = self.calculate_bmi(current_weight, height)
            self.bmi_label.set_markup(f"<span font_desc='24'>{bmi:.1f}</span>")
            
            # Set category with correct color format
            r, g, b = BMI_COLORS.get(category, (0.5, 0.5, 0.5))
            r_int, g_int, b_int = int(r*255), int(g*255), int(b*255)
            color_hex = f"#{r_int:02x}{g_int:02x}{b_int:02x}"  # Convert to hex color
            
            self.bmi_category.set_markup(f"<span font_desc='16' foreground='{color_hex}'>{category}</span>")
            
            # Update BMI scale
            self.bmi_scale.set_bmi(bmi)
        
        # Enable/disable controls based on measuring state
        self.adj_spin.set_sensitive(not measuring)
        self.height_spin.set_sensitive(not measuring)
        self.feet_spin.set_sensitive(not measuring)
        self.inches_spin.set_sensitive(not measuring)
        self.gender_dropdown.set_sensitive(not measuring)
        self.metric_button.set_sensitive(not measuring)
        self.imperial_button.set_sensitive(not measuring)
        
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
        about.set_program_name("Weii")
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
            status_message = "User stepped off"
            break
        if len(data) == 0 and measurement < threshold:
            # This measurement is too light and measurement hasn't yet started, ignore.
            continue
        data.append(measurement)
        if len(data) == 1:
            status_message = "Measuring..."
        if len(data) >= samples:
            # We have enough samples now.
            break
        
        # Update status with simple message
        if len(data) % 20 == 0:
            status_message = "Measuring..."
            
    device.close()
    return data

def measure_weight(
    adjust: float,
    minlimit: float,
    terse: bool,
    fake: bool = False,
) -> float:
    """Perform one weight measurement."""
    global status_message
    
    status_message = "Waiting for balance board..."
    while not fake:
        board = get_board_device()
        if board:
            break
        time.sleep(0.5)
    status_message = "Please step on board"
    
    if fake:
        weight_data = [85.2] * 200
    else:
        weight_data = read_data(board, 200, threshold=minlimit)
        
    final_weight = statistics.median(weight_data)
    final_weight += adjust
    
    if terse:
        debug(f"{final_weight:.1f}", force=True)
    else:
        status_message = "Done"
        
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