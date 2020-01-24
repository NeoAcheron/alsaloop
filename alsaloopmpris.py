#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
# Author: Modul 9 <info@hifiberry.com>
# Based on mpDris2 by
#          Jean-Philippe Braun <eon@patapon.info>,
#          Mantas Mikulėnas <grawity@gmail.com>
# Based on mpDris by:
#          Erik Karlsson <pilo@ayeon.org>
# Some bits taken from quodlibet mpris plugin by:
#           <christoph.reiter@gmx.at>

import sys
import logging
import time
import threading
import fcntl
import os
import subprocess
import json
import signal
import configparser
import struct
import math

import dbus.service
from dbus.mainloop.glib import DBusGMainLoop

from alsaaudio import \
    pcms, cards, PCM, PCM_PLAYBACK, PCM_CAPTURE, PCM_NORMAL, PCM_NONBLOCK, \
    PCM_FORMAT_S16_LE, PCM_FORMAT_S32_LE


try:
    from gi.repository import GLib
    using_gi_glib = True
except ImportError:
    import glib as GLib

identity = "alsaloop client"

PLAYBACK_STOPPED = "stopped"
PLAYBACK_PAUSED = "pause"
PLAYBACK_PLAYING = "playing"
PLAYBACK_UNKNOWN = "unkown"

# python dbus bindings don't include annotations and properties
MPRIS2_INTROSPECTION = """<node name="/org/mpris/MediaPlayer2">
  <interface name="org.freedesktop.DBus.Introspectable">
    <method name="Introspect">
      <arg direction="out" name="xml_data" type="s"/>
    </method>
  </interface>
  <interface name="org.freedesktop.DBus.Properties">
    <method name="Get">
      <arg direction="in" name="interface_name" type="s"/>
      <arg direction="in" name="property_name" type="s"/>
      <arg direction="out" name="value" type="v"/>
    </method>
    <method name="GetAll">
      <arg direction="in" name="interface_name" type="s"/>
      <arg direction="out" name="properties" type="a{sv}"/>
    </method>
    <method name="Set">
      <arg direction="in" name="interface_name" type="s"/>
      <arg direction="in" name="property_name" type="s"/>
      <arg direction="in" name="value" type="v"/>
    </method>
    <signal name="PropertiesChanged">
      <arg name="interface_name" type="s"/>
      <arg name="changed_properties" type="a{sv}"/>
      <arg name="invalidated_properties" type="as"/>
    </signal>
  </interface>
  <interface name="org.mpris.MediaPlayer2">
    <method name="Raise"/>
    <method name="Quit"/>
    <annotation name="org.freedesktop.DBus.Property.EmitsChangedSignal" value="false"/>
    <property name="CanQuit" type="b" access="read"/>
    <property name="CanRaise" type="b" access="read"/>
    <property name="HasTrackList" type="b" access="read"/>
    <property name="Identity" type="s" access="read"/>
    <property name="DesktopEntry" type="s" access="read"/>
    <property name="SupportedUriSchemes" type="as" access="read"/>
    <property name="SupportedMimeTypes" type="as" access="read"/>
  </interface>
  <interface name="org.mpris.MediaPlayer2.Player">
    <method name="Next"/>
    <method name="Previous"/>
    <method name="Pause"/>
    <method name="PlayPause"/>
    <method name="Stop"/>
    <method name="Play"/>
    <method name="Seek">
      <arg direction="in" name="Offset" type="x"/>
    </method>
    <method name="SetPosition">
      <arg direction="in" name="TrackId" type="o"/>
      <arg direction="in" name="Position" type="x"/>
    </method>
    <method name="OpenUri">
      <arg direction="in" name="Uri" type="s"/>
    </method>
    <signal name="Seeked">
      <arg name="Position" type="x"/>
    </signal>
    <property name="PlaybackStatus" type="s" access="read">
      <annotation name="org.freedesktop.DBus.Property.EmitsChangedSignal" value="true"/>
    </property>
    <property name="LoopStatus" type="s" access="readwrite">
      <annotation name="org.freedesktop.DBus.Property.EmitsChangedSignal" value="true"/>
    </property>
    <property name="Rate" type="d" access="readwrite">
      <annotation name="org.freedesktop.DBus.Property.EmitsChangedSignal" value="true"/>
    </property>
    <property name="Shuffle" type="b" access="readwrite">
      <annotation name="org.freedesktop.DBus.Property.EmitsChangedSignal" value="true"/>
    </property>
    <property name="Metadata" type="a{sv}" access="read">
      <annotation name="org.freedesktop.DBus.Property.EmitsChangedSignal" value="true"/>
    </property>
    <property name="Volume" type="d" access="readwrite">
      <annotation name="org.freedesktop.DBus.Property.EmitsChangedSignal" value="false"/>
    </property>
    <property name="Position" type="x" access="read">
      <annotation name="org.freedesktop.DBus.Property.EmitsChangedSignal" value="false"/>
    </property>
    <property name="MinimumRate" type="d" access="read">
      <annotation name="org.freedesktop.DBus.Property.EmitsChangedSignal" value="true"/>
    </property>
    <property name="MaximumRate" type="d" access="read">
      <annotation name="org.freedesktop.DBus.Property.EmitsChangedSignal" value="true"/>
    </property>
    <property name="CanGoNext" type="b" access="read">
      <annotation name="org.freedesktop.DBus.Property.EmitsChangedSignal" value="true"/>
    </property>
    <property name="CanGoPrevious" type="b" access="read">
      <annotation name="org.freedesktop.DBus.Property.EmitsChangedSignal" value="true"/>
    </property>
    <property name="CanPlay" type="b" access="read">
      <annotation name="org.freedesktop.DBus.Property.EmitsChangedSignal" value="true"/>
    </property>
    <property name="CanPause" type="b" access="read">
      <annotation name="org.freedesktop.DBus.Property.EmitsChangedSignal" value="true"/>
    </property>
    <property name="CanSeek" type="b" access="read">
      <annotation name="org.freedesktop.DBus.Property.EmitsChangedSignal" value="true"/>
    </property>
    <property name="CanControl" type="b" access="read">
      <annotation name="org.freedesktop.DBus.Property.EmitsChangedSignal" value="false"/>
    </property>
  </interface>
</node>"""


class ALSALoopWrapper(threading.Thread):
    """ Wrapper to handle internal alsaloop
    """

    def __init__(self, auto_start = True):
        super().__init__()
        self.playerid = None
        self.playback_status = "stopped"
        self.metadata = {}

        self.dbus_service = None

        self.bus = dbus.SessionBus()
        self.received_data = False
        
        self.auto_start = auto_start

        self.pcmformat = PCM_FORMAT_S16_LE
        self.buffersize = 512
        self.samplerate = 48000
        
        self.playback = None
        self.record = None
        
    def __del__(self):
        if self.playback is not None:
            self.playback = None
            
        if self.record is not None:
            self.record = None
            
        

    def run(self):
        try:
            self.dbus_service = MPRISInterface()
#            self.mainloop()
            self.simple_loop()

        except Exception as e:
            logging.error("ALSALoopWrapper thread exception: %s", e)
            logging.exception(e)
            sys.exit(1)

        logging.error("ALSALoopWrapper thread died - this should not happen")
        sys.exit(1)
        
        
 
                

    def record_device(self):
        if self.record is not None:
            return self.record
        
        inp = PCM(PCM_CAPTURE, PCM_NONBLOCK, device="sysdefault:CARD=sndrpihifiberry")

        # Set attributes: Stereo, 44100 Hz, 16 bit little endian samples
        inp.setchannels(2)
        inp.setrate(44100)
        inp.setformat(PCM_FORMAT_S16_LE)
        inp.setperiodsize(1024)

        self.record = inp
    
        return self.record

    def playback_device(self):
        if self.playback is not None:
            return self.playback

        out = PCM(PCM_PLAYBACK, device="sysdefault:CARD=sndrpihifiberry")

        # Set attributes:Stereo, 44100 Hz, 16 bit little endian frames
        out.setchannels(2)
        out.setrate(44100)
        out.setformat(PCM_FORMAT_S16_LE)

        # The period size controls the internal number of frames per period.
        # The significance of this parameter is documented in the ALSA api.
        out.setperiodsize(1024)        
        
        self.playback = out
        return self.playback
    
    
class alsaloopWrapper(threading.Thread):
    """ Wrapper to handle alsaloopclient
    """

    def __init__(self, alsaloopserver):
        super().__init__()
        self.playerid = None
        self.playback_status = "stopped"
        self.metadata = {}
        self.server = alsaloopserver

        self.dbus_service = None

        self.bus = dbus.SessionBus()
        self.received_data = False

        self.alsaloopclient = None
        self.streamname = ""

    def run(self):
        try:
            self.dbus_service = MPRISInterface()

            self.mainloop()

        except Exception as e:
            logging.error("alsaloopwrapper thread exception: %s", e)
            sys.exit(1)

        logging.error("alsaloopwrapper thread died - this should not happen")
        sys.exit(1)

    def mainloop_external(self):
        current_playback_status = None
        while True:
            if self.playback_status != current_playback_status:
                current_playback_status = self.playback_status

                # Changed - do something

                if self.playback_status == PLAYBACK_PLAYING:
                    if self.alsaloopclient is None:
                        logging.info("pausing other players")
                        subprocess.run(["/opt/hifiberry/bin/pause-all", "alsaloop"])
                        logging.info("starting alsaloop")
                        self.alsaloopclient = \
                            subprocess.Popen("/bin/alsaloop -P default -r i48000 -f S32_LE -t 100000 -S 1",
                                              stdout=subprocess.PIPE,
                                              stderr=subprocess.PIPE,
                                              shell=True)
                        logging.info("alsaloop now running in background")
                    else:
                        logging.error("alsaloop process seems to be running already")

                else:
                    # Not playing: kill client
                    if self.alsaloopclient is None:
                        logging.info("No alsaloop client running, doing nothing")
                    else:
                        logging.info("Killing alsaloop client, doing nothing")
                        self.alsaloopclient.kill()
                        # Wait until it died
                        _outs, _errs = self.alsaloopclient.communicate()
                        self.alsaloopclient = None

                # Playback status has changed, now inform DBUS
                self.update_metadata()
                self.dbus_service.update_property('org.mpris.MediaPlayer2.Player',
                                                  'PlaybackStatus')

            # Check if alsaloop is still running
            if self.alsaloopclient:
                if self.alsaloopclient.poll() is not None:
                    logging.warning("snapclient died")
                    self.playback_status = PLAYBACK_STOPPED
                    self.alsaloopclient = None


            time.sleep(0.2)



    def mainloop(self, detect_threshold=300):
        """ 
        This is not yet working as the alsaudio stuff doesn't seem to work stable 
        in a background thread
        """
        
        current_playback_status = None
        finished = False
        signal_detected = False

        record = self.record_device()

        while not finished:
            
            if signal_detected and self.auto_start:
                self.playback_status = PLAYBACK_PLAYING
            
            if not(signal_detected):
                self.playback_status = PLAYBACK_STOPPED
                
            self.playback_status = PLAYBACK_PLAYING
            
            if self.playback_status != current_playback_status:
                logging.error("playback status changed from %s to %s",
                             current_playback_status, self.playback_status)
                if self.playback_status == PLAYBACK_PLAYING:
                    logging.error("opening playback device")
                    playback = self.playback_device()
                    logging.error("opened playback device")
                else:
                    playback = None
            else:
                logging.debug("playback status unchanged")
            current_playback_status = self.playback_status

            size, data = record.read()
            if not(size):
                time.sleep(0.001);
                continue

            if (len(data) % 4) != 0:
                logging.error("oops %s", len(data))
            
            # do something with the data
#             i = 0
#             rms = 0
#             while i < len(data):
#                 l, r = struct.unpack_from("<hh", data, i)
#                 rms = rms + l * l + r * r
#                 i += 4
#                 if abs(l) > detect_threshold or abs(r) > detect_threshold:
#                     signal_detected = True
# 
#             rms = math.sqrt(rms / self.buffersize)
            
            # DEBUGGING ONLY
                        

            if self.playback_status == PLAYBACK_PLAYING:
                try:
                    playback.write(data)
                except Exception as e:
                    logging.exception(e)
                    logging.warning("could not write output to sound card, stopping")
                    self.playback_status = PLAYBACK_STOPPED
                    
            time.sleep(.001)

    def update_metadata(self):
        if self.alsaloopclient is not None:
            self.metadata["xesam:url"] = \
                "alsaloop://{}/{}".format(self.server, self.streamname)

        self.dbus_service.update_property('org.mpris.MediaPlayer2.Player',
                                                  'Metadata')


class MPRISInterface(dbus.service.Object):
    ''' The base object of an MPRIS player '''

    PATH = "/org/mpris/MediaPlayer2"
    INTROSPECT_INTERFACE = "org.freedesktop.DBus.Introspectable"
    PROP_INTERFACE = dbus.PROPERTIES_IFACE

    def __init__(self):
        dbus.service.Object.__init__(self, dbus.SystemBus(),
                                     MPRISInterface.PATH)
        self.name = "org.mpris.MediaPlayer2.alsaloop"
        self.bus = dbus.SystemBus()
        self.uname = self.bus.get_unique_name()
        self.dbus_obj = self.bus.get_object("org.freedesktop.DBus",
                                            "/org/freedesktop/DBus")
        self.dbus_obj.connect_to_signal("NameOwnerChanged",
                                        self.name_owner_changed_callback,
                                        arg0=self.name)

        self.acquire_name()
        logging.info("name on DBus aqcuired")

    def name_owner_changed_callback(self, name, old_owner, new_owner):
        if name == self.name and old_owner == self.uname and new_owner != "":
            try:
                pid = self._dbus_obj.GetConnectionUnixProcessID(new_owner)
            except:
                pid = None
            logging.info("Replaced by %s (PID %s)" %
                         (new_owner, pid or "unknown"))
            loop.quit()

    def acquire_name(self):
        self.bus_name = dbus.service.BusName(self.name,
                                             bus=self.bus,
                                             allow_replacement=True,
                                             replace_existing=True)

    def release_name(self):
        if hasattr(self, "_bus_name"):
            del self.bus_name

    ROOT_INTERFACE = "org.mpris.MediaPlayer2"
    ROOT_PROPS = {
        "CanQuit": (False, None),
        "CanRaise": (False, None),
        "DesktopEntry": ("alsaloopmpris", None),
        "HasTrackList": (False, None),
        "Identity": (identity, None),
        "SupportedUriSchemes": (dbus.Array(signature="s"), None),
        "SupportedMimeTypes": (dbus.Array(signature="s"), None)
    }

    @dbus.service.method(INTROSPECT_INTERFACE)
    def Introspect(self):
        return MPRIS2_INTROSPECTION

    def get_playback_status():
        status = alsaloop_wrapper.playback_status
        return {PLAYBACK_PLAYING: 'Playing',
                PLAYBACK_PAUSED: 'Paused',
                PLAYBACK_STOPPED: 'Stopped',
                PLAYBACK_UNKNOWN: 'Unknown'}[status]

    def get_metadata():
        return dbus.Dictionary(alsaloop_wrapper.metadata, signature='sv')

    PLAYER_INTERFACE = "org.mpris.MediaPlayer2.Player"
    PLAYER_PROPS = {
        "PlaybackStatus": (get_playback_status, None),
        "Rate": (1.0, None),
        "Metadata": (get_metadata, None),
        "MinimumRate": (1.0, None),
        "MaximumRate": (1.0, None),
        "CanGoNext": (False, None),
        "CanGoPrevious": (False, None),
        "CanPlay": (True, None),
        "CanPause": (True, None),
        "CanSeek": (False, None),
        "CanControl": (False, None),
    }

    PROP_MAPPING = {
        PLAYER_INTERFACE: PLAYER_PROPS,
        ROOT_INTERFACE: ROOT_PROPS,
    }

    @dbus.service.signal(PROP_INTERFACE, signature="sa{sv}as")
    def PropertiesChanged(self, interface, changed_properties,
                          invalidated_properties):
        pass

    @dbus.service.method(PROP_INTERFACE,
                         in_signature="ss", out_signature="v")
    def Get(self, interface, prop):
        getter, _setter = self.PROP_MAPPING[interface][prop]
        if callable(getter):
            return getter()
        return getter

    @dbus.service.method(PROP_INTERFACE,
                         in_signature="ssv", out_signature="")
    def Set(self, interface, prop, value):
        _getter, setter = self.PROP_MAPPING[interface][prop]
        if setter is not None:
            setter(value)

    @dbus.service.method(PROP_INTERFACE,
                         in_signature="s", out_signature="a{sv}")
    def GetAll(self, interface):
        read_props = {}
        props = self.PROP_MAPPING[interface]
        for key, (getter, _setter) in props.items():
            if callable(getter):
                getter = getter()
            read_props[key] = getter
        return read_props

    def update_property(self, interface, prop):
        getter, _setter = self.PROP_MAPPING[interface][prop]
        if callable(getter):
            value = getter()
        else:
            value = getter
        logging.debug('Updated property: %s = %s' % (prop, value))
        self.PropertiesChanged(interface, {prop: value}, [])
        return value

    # Player methods
    @dbus.service.method(PLAYER_INTERFACE, in_signature='', out_signature='')
    def Pause(self):
        logging.debug("received DBUS pause")
        alsaloop_wrapper.playback_status = PLAYBACK_STOPPED
        return

    @dbus.service.method(PLAYER_INTERFACE, in_signature='', out_signature='')
    def PlayPause(self):
        logging.debug("received DBUS play/pause")
        status = alsaloop_wrapper.playback_status

        if status == PLAYBACK_PLAYING:
            alsaloop_wrapper.playback_status = PLAYBACK_STOPPED
        else:
            alsaloop_wrapper.playback_status = PLAYBACK_PLAYING
        return

    @dbus.service.method(PLAYER_INTERFACE, in_signature='', out_signature='')
    def Stop(self):
        logging.debug("received DBUS stop")
        alsaloop_wrapper.playback_status = PLAYBACK_STOPPED
        return

    @dbus.service.method(PLAYER_INTERFACE, in_signature='', out_signature='')
    def Play(self):
        alsaloop_wrapper.playback_status = PLAYBACK_PLAYING
        return


def stopalsaloop(signalNumber, frame):
    logging.info("received USR1, stopping alsaloop")
    alsaloop_wrapper.playback_status = PLAYBACK_STOPPED


def parse_config(debugmode=False):
    config = configparser.ConfigParser()
    try:
        config.read("/etc/alsaloop.conf")
        logging.info("read /etc/alsaloop.conf")
    except:
        pass
    
    alsaloopWrapper = ALSALoopWrapper()

    # Auto start for alsaloop
    if config.getboolean("alsaloop", "autostart", fallback=True):
        alsaloopWrapper.playback_status = PLAYBACK_PLAYING

    return alsaloopWrapper


if __name__ == '__main__':
    DBusGMainLoop(set_as_default=True)

    if len(sys.argv) > 1:
        if "-v" in sys.argv:
            logging.basicConfig(format='%(levelname)s: %(name)s - %(message)s',
                                level=logging.DEBUG)
            logging.debug("enabled verbose logging")
    else:
        logging.basicConfig(format='%(levelname)s: %(name)s - %(message)s',
                            level=logging.INFO)

    # Set up the main loop
    loop = GLib.MainLoop()

    signal.signal(signal.SIGUSR1, stopalsaloop)

    server = "192.168.30.110"

    # Create wrapper to handle connection failures with MPD more gracefully
    try:
        alsaloop_wrapper = parse_config()
        alsaloop_wrapper.start()
        logging.info("alsaloop wrapper thread started")
    except dbus.exceptions.DBusException as e:
        logging.error("DBUS error: %s", e)
        sys.exit(1)

    time.sleep(2)
    if not (alsaloop_wrapper.is_alive()):
        logging.error("alsaloop connector thread died, exiting")
        sys.exit(1)

    # Run idle loop
    try:
        logging.info("main loop started")
        loop.run()
    except KeyboardInterrupt:
        logging.debug('Caught SIGINT, exiting.')
