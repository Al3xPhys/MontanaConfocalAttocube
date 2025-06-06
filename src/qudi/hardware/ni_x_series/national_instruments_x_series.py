# -*- coding: utf-8 -*-
"""
This file contains the Qudi dummy module for the confocal scanner.

Copyright (c) 2021, the qudi developers. See the AUTHORS.md file at the top-level directory of this
distribution and on <https://github.com/Ulm-IQO/qudi-iqo-modules/>

This file is part of qudi.

Qudi is free software: you can redistribute it and/or modify it under the terms of
the GNU Lesser General Public License as published by the Free Software Foundation,
either version 3 of the License, or (at your option) any later version.

Qudi is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY;
without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.
See the GNU Lesser General Public License for more details.

You should have received a copy of the GNU Lesser General Public License along with qudi.
If not, see <https://www.gnu.org/licenses/>.
"""

import time
import numpy as np
from PySide2 import QtCore
import PyDAQmx as daq
from fysom import FysomError
from qudi.core.configoption import ConfigOption
from qudi.util.mutex import RecursiveMutex
from qudi.interface.scanning_probe_interface import ScanningProbeInterface, ScanData, CoordinateTransformMixin
from qudi.interface.scanning_probe_interface import ScanConstraints, ScannerAxis, ScannerChannel


class NationalInstrumentsXSeriesBare(ScanningProbeInterface):
    """
    Dummy scanning probe microscope. Produces a picture with several gaussian spots.

    Example config for copy-paste:

    scanning_probe_dummy:
        module.Class: 'scanning_probe_dummy.ScanningProbeDummy'
        options:
            spot_density: 4e6           # in 1/m², optional
            position_ranges:
                x: [0, 200e-6]
                y: [0, 200e-6]
                z: [-100e-6, 100e-6]
            frequency_ranges:
                x: [1, 5000]
                y: [1, 5000]
                z: [1, 1000]
            resolution_ranges:
                x: [1, 10000]
                y: [1, 10000]
                z: [2, 1000]
            position_accuracy:
                x: 10e-9
                y: 10e-9
                z: 50e-9
    """
    # TODO Bool indicators deprecated; Change in scanning probe toolchain

    _threaded = True

    # config options
    _position_ranges = ConfigOption(name='position_ranges', missing='error')
    _frequency_ranges = ConfigOption(name='frequency_ranges', missing='error')
    _resolution_ranges = ConfigOption(name='resolution_ranges', missing='error')
    _position_accuracy = ConfigOption(name='position_accuracy', missing='error')
    _spot_density = ConfigOption(name='spot_density', default=1e12/8)  # in 1/m²
    _spot_depth_range = ConfigOption(name='spot_depth_range', default=(-500e-9, 500e-9))
    _spot_size_dist = ConfigOption(name='spot_size_dist', default=(100e-9, 15e-9))
    _spot_amplitude_dist = ConfigOption(name='spot_amplitude_dist', default=(2e5, 4e4))
    _require_square_pixels = ConfigOption(name='require_square_pixels', default=False)

    _a_voltage = ConfigOption(name='a_voltage', missing='error')
    _a_other = ConfigOption(name='a_other', missing='error')
    _samples_number = ConfigOption(name='samples_number', missing='error')
    _clock_channel = ConfigOption(name='clock_channel', missing='error')
    _scanner_clock_channel = ConfigOption(name='scanner_clock_channel', missing='error')
    _photon_sources = ConfigOption(name='photon_sources', missing='error')
    _counter_channels = ConfigOption(name='counter_channels', missing='error')
    _scanner_counter_channels = ConfigOption(name='scanner_counter_channels', missing='error')
    _gate_in_channel = ConfigOption(name='gate_in_channel', missing='error')
    _odmr_trigger_channel = ConfigOption(name='odmr_trigger_channel', missing='error')
    _odmr_trigger_line = ConfigOption(name='odmr_trigger_line', missing='error')
    _odmr_switch_line = ConfigOption(name='odmr_switch_line', missing='error')
    _counting_edge_rising = ConfigOption(name='counting_edge_rising', missing='error')
    _clock_frequency = ConfigOption(name='clock_frequency', missing='error')
    _scanner_clock_frequency = ConfigOption(name='scanner_clock_frequency', missing='error')
    _scanner_ao_channels = ConfigOption(name='scanner_ao_channels', missing='error')
    _scanner_voltage_ranges = ConfigOption(name='scanner_voltage_ranges', missing = 'error')
    _scanner_ai_channels = ConfigOption(name = 'scanner_ai_channels', missing = 'error')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Scan process parameters
        self._current_scan_frequency = -1
        self._current_scan_ranges = [tuple(), tuple()]
        self._current_scan_axes = tuple()
        self._current_scan_resolution = tuple()
        self._current_position = dict()
        self._scan_image = None
        self._scan_data = None

        # Randomized spot positions
        self._spots = dict()
        # "Hardware" constraints
        self._constraints = None
        # Mutex for access serialization
        self._thread_lock = RecursiveMutex()

        self.__scan_start = 0
        self.__last_line = -1
        self.__update_timer = None

        # handle to the uncorrected scanner instance, not wrapped by a potential CoordinateTransformMixin
        # that transforms to a tilted, virtual coordinate system.
        self.bare_scanner = NationalInstrumentsXSeriesBare

    def on_activate(self):
        """ Initialisation performed during activation of the module.
        """
        # Set default process values
        self._current_scan_ranges = tuple(tuple(rng) for rng in tuple(self._position_ranges.values())[:2])
        self._current_scan_axes = tuple(self._position_ranges)[:2]
        self._current_scan_frequency = max(self._frequency_ranges[self._current_scan_axes[0]])
        self._current_scan_resolution = tuple([100] * len(self._current_scan_axes))
        self._current_position = {ax: min(rng) + (max(rng) - min(rng)) / 2 for ax, rng in
                                  self._position_ranges.items()}
        self._scan_image = np.zeros(self._current_scan_resolution)
        self._scan_data = None

        self._counter_daq_tasks = []
        self._counter_analog_daq_task = None
        self._clock_daq_task = None
        self._scanner_clock_daq_task = None
        self._scanner_ao_task = None
        self._scanner_counter_daq_tasks = []
        self._line_length = None
        self._odmr_length = None
        self._gated_counter_daq_task = None
        self._scanner_analog_daq_task = None
        self._odmr_pulser_daq_task = None
        self._oversampling = 0
        self._lock_in_active = False

        if self._a_other:
            self._current_position = np.zeros(len(self._scanner_ao_channels) - 1)
        else:
            self._current_position = np.zeros(len(self._scanner_ao_channels))
        #            self._current_position.append(0)
        #            self._position_range.append([0, 100e-6])

        if len(self._scanner_ao_channels) > len(self._scanner_voltage_ranges):
            self.log.error(
                'Specify at least as many scanner_voltage_ranges as scanner_ao_channels!')

        if len(self._positional_channels()) > len(self._position_ranges):
            self.log.error(
                'Specify at least as many scanner_position_ranges as positional scanner_ao_channels!')

        if len(self._scanner_counter_channels) + len(self._scanner_ai_channels) < 1:
            self.log.error(
                'Specify at least one counter or analog input channel for the scanner!')

        # Analog output is always needed and it does not interfere with the
        # rest, so start it always and leave it running
        if self._start_analog_output() < 0:
            self.log.error('Failed to start analog output.')
            raise Exception('Failed to start NI Card module due to analog output failure.')

        # Once the analog output is available, set the AOM channel if in use
        if self._a_other:
            self.set_voltage(self._a_voltage)

        # Create fixed maps of spots for each scan axes configuration
        # self._randomize_new_spots()

        # Generate static constraints
        axes = list()
        for ax, ax_range in self._position_ranges.items():
            dist = max(ax_range) - min(ax_range)
            axes.append(ScannerAxis(name=ax,
                                    unit='m',
                                    value_range=ax_range,
                                    step_range=(0, dist),
                                    resolution_range=self._resolution_ranges[ax],
                                    frequency_range=self._frequency_ranges[ax]))
        channels = [ScannerChannel(name='fluorescence', unit='c/s', dtype=np.float64),
                    ScannerChannel(name='APD events', unit='count', dtype=np.float64)]

        self._constraints = ScanConstraints(axes=axes,
                                            channels=channels,
                                            backscan_configurable=False,
                                            has_position_feedback=False,
                                            square_px_only=False)
        self.__scan_start = 0
        self.__last_line = -1
        self.__update_timer = QtCore.QTimer()
        self.__update_timer.setSingleShot(True)
        self.__update_timer.timeout.connect(self.get_scan_data, QtCore.Qt.QueuedConnection)
        return

    def _positional_channels(self):
        if self._a_other:
            return self._scanner_ao_channels[0:-1]
        else:
            return self._scanner_ao_channels

    def on_deactivate(self):
        """ Deactivate properly the confocal scanner dummy.
        """
        self.reset()
        # free memory
        self._spots = dict()
        self._scan_image = None
        try:
            self.__update_timer.stop()
        except:
            pass
        self.__update_timer.timeout.disconnect()

    @property
    def scan_settings(self):
        with self._thread_lock:
            settings = {'axes': tuple(self._current_scan_axes),
                        'range': tuple(self._current_scan_ranges),
                        'resolution': tuple(self._current_scan_resolution),
                        'frequency': self._current_scan_frequency}
            return settings

    def _randomize_new_spots(self):
        self._spots = dict()
        for x_axis, x_range in self._position_ranges.items():
            for y_axis, y_range in self._position_ranges.items():
                if x_axis == y_axis:
                    continue
                x_min, x_max = min(x_range), max(x_range)
                y_min, y_max = min(y_range), max(y_range)
                spot_count = int(round((x_max - x_min) * (y_max - y_min) * self._spot_density))

                # Fill in random spot information
                spot_dict = dict()
                # total number of spots
                spot_dict['count'] = spot_count
                # spot positions as (x, y) tuples
                spot_dict['pos'] = np.empty((spot_count, 2))
                spot_dict['pos'][:, 0] = np.random.uniform(x_min, x_max, spot_count)
                spot_dict['pos'][:, 1] = np.random.uniform(y_min, y_max, spot_count)
                # spot sizes as (sigma_x, sigma_y) tuples
                spot_dict['sigma'] = np.random.normal(
                    self._spot_size_dist[0], self._spot_size_dist[1], (spot_count, 2))
                # spot amplitudes
                spot_dict['amp'] = np.random.normal(
                    self._spot_amplitude_dist[0], self._spot_amplitude_dist[1], spot_count)
                # spot angle
                spot_dict['theta'] = np.random.uniform(0, np.pi, spot_count)

                # Add information to _spots dict
                self._spots[(x_axis, y_axis)] = spot_dict

    def reset(self):
        """ Resets the hardware, so the connection is lost and other programs can access it.

        @return int: error code (0:OK, -1:error)
        """
        with self._thread_lock:
            if self.module_state() == 'locked':
                self.module_state.unlock()
            self.log.debug('Scanning probe dummy has been reset.')
            return 0

    def get_constraints(self):
        """

        @return:
        """
        #self.log.debug('Scanning probe dummy "get_constraints" called.')
        return self._constraints

    def configure_scan(self, scan_settings):
        """

        @param dict scan_settings:

        @return dict: ALL actually set scan settings
        """
        with self._thread_lock:
            self.log.debug('Scanning probe dummy "configure_scan" called.')
            # Sanity checking
            if self.module_state() != 'idle':
                self.log.error('Unable to configure scan parameters while scan is running. '
                               'Stop scanning and try again.')
                return True, self.scan_settings

            axes = scan_settings.get('axes', self._current_scan_axes)
            ranges = tuple(
                (min(r), max(r)) for r in scan_settings.get('range', self._current_scan_ranges)
            )
            resolution = scan_settings.get('resolution', self._current_scan_resolution)
            frequency = float(scan_settings.get('frequency', self._current_scan_frequency))

            if 'axes' in scan_settings:
                if not set(axes).issubset(self._position_ranges):
                    self.log.error('Unknown axes names encountered. Valid axes are: {0}'
                                   ''.format(set(self._position_ranges)))
                    return True, self.scan_settings

            if len(axes) != len(ranges) or len(axes) != len(resolution):
                self.log.error('"axes", "range" and "resolution" must have same length.')
                return True, self.scan_settings
            for i, ax in enumerate(axes):
                for axis_constr in self._constraints.axes.values():
                    if ax == axis_constr.name:
                        break
                if ranges[i][0] < axis_constr.min_value or ranges[i][1] > axis_constr.max_value:
                    self.log.error('Scan range out of bounds for axis "{0}". Maximum possible range'
                                   ' is: {1}'.format(ax, axis_constr.value_range))
                    return True, self.scan_settings
                if resolution[i] < axis_constr.min_resolution or resolution[i] > axis_constr.max_resolution:
                    self.log.error('Scan resolution out of bounds for axis "{0}". Maximum possible '
                                   'range is: {1}'.format(ax, axis_constr.resolution_range))
                    return True, self.scan_settings
                if i == 0:
                    if frequency < axis_constr.min_frequency or frequency > axis_constr.max_frequency:
                        self.log.error('Scan frequency out of bounds for fast axis "{0}". Maximum '
                                       'possible range is: {1}'
                                       ''.format(ax, axis_constr.frequency_range))
                        return True, self.scan_settings

            self._current_scan_resolution = tuple(resolution)
            self._current_scan_ranges = ranges
            self._current_scan_axes = tuple(axes)
            self._current_scan_frequency = frequency
            return False, self.scan_settings

    def move_absolute(self, position, velocity=None, blocking=False):
        """ Move the scanning probe to an absolute position as fast as possible or with a defined
        velocity.

        Log error and return current target position if something fails or a 1D/2D scan is in
        progress.
        """
        with self._thread_lock:
            # self.log.debug('Scanning probe dummy "move_absolute" called.')
            if self.module_state() != 'idle':
                self.log.error('Scanning in progress. Unable to move to position.')
            elif not set(position).issubset(self._position_ranges):
                self.log.error('Invalid axes encountered in position dict. Valid axes are: {0}'
                               ''.format(set(self._position_ranges)))
            else:
                move_distance = {ax: np.abs(pos - self._current_position[ax]) for ax, pos in
                                 position.items()}
                if velocity is None:
                    move_time = 0.01
                else:
                    move_time = max(0.01, np.sqrt(
                        np.sum(dist ** 2 for dist in move_distance.values())) / velocity)
                time.sleep(move_time)
                self._current_position.update(position)
            return self._current_position

    def move_relative(self, distance, velocity=None, blocking=False):
        """ Move the scanning probe by a relative distance from the current target position as fast
        as possible or with a defined velocity.

        Log error and return current target position if something fails or a 1D/2D scan is in
        progress.
        """
        with self._thread_lock:
            self.log.debug('Scanning probe dummy "move_relative" called.')
            if self.module_state() != 'idle':
                self.log.error('Scanning in progress. Unable to move relative.')
            elif not set(distance).issubset(self._position_ranges):
                self.log.error('Invalid axes encountered in distance dict. Valid axes are: {0}'
                               ''.format(set(self._position_ranges)))
            else:
                new_pos = {ax: self._current_position[ax] + dist for ax, dist in distance.items()}
                if velocity is None:
                    move_time = 0.01
                else:
                    move_time = max(0.01, np.sqrt(
                        np.sum(dist ** 2 for dist in distance.values())) / velocity)
                time.sleep(move_time)
                self._current_position.update(new_pos)
            return self._current_position

    def get_target(self):
        """ Get the current target position of the scanner hardware.

        @return dict: current target position per axis.
        """
        with self._thread_lock:
            #self.log.debug('Scanning probe dummy "get_target" called.')
            return self._current_position.copy()

    def get_position(self):
        """ Get a snapshot of the actual scanner position (i.e. from position feedback sensors).

        @return dict: current target position per axis.
        """
        with self._thread_lock:
            #self.log.debug('Scanning probe dummy "get_position" called.')
            position = {ax: pos + np.random.normal(0, self._position_accuracy[ax]) for ax, pos in
                        self._current_position.items()}
            return position

    def start_scan(self):
        """
        @return:
        """
        with self._thread_lock:
            self.log.debug('start_scan" called.')
            if self.module_state() != 'idle':
                self.log.error('Can not start scan. Scan already in progress.')
                return -1
            self.module_state.lock()
            if len(self._current_scan_axes) == 1:
                for axes, d in self._spots.items():
                    if axes[0] == self._current_scan_axes[0]:
                        sim_data = d
            else:
                sim_data = self._spots[self._current_scan_axes]
            number_of_spots = sim_data['count']
            positions = sim_data['pos']
            amplitudes = sim_data['amp']
            sigmas = sim_data['sigma']
            thetas = sim_data['theta']

            x_values = np.linspace(self._current_scan_ranges[0][0],
                                   self._current_scan_ranges[0][1],
                                   self._current_scan_resolution[0])
            if len(self._current_scan_axes) == 2:
                y_values = np.linspace(self._current_scan_ranges[1][0],
                                       self._current_scan_ranges[1][1],
                                       self._current_scan_resolution[1])
            else:
                y_values = np.linspace(self._current_position['y'], self._current_position['y'], 1)
            xy_grid = self._init_scan_grid(x_values, y_values)

            include_dist = self._spot_size_dist[0] + 5 * self._spot_size_dist[1]
            self._scan_image = np.random.uniform(0, 2e4, self._current_scan_resolution)
            for i in range(number_of_spots):
                if positions[i][0] < self._current_scan_ranges[0][0] - include_dist:
                    continue
                if positions[i][0] > self._current_scan_ranges[0][1] + include_dist:
                    continue
                if len(self._current_scan_axes) == 1:
                    if positions[i][1] < self._current_position['y'] - include_dist:
                        continue
                    if positions[i][1] > self._current_position['y'] + include_dist:
                        continue
                else:
                    if positions[i][1] < self._current_scan_ranges[1][0] - include_dist:
                        continue
                    if positions[i][1] > self._current_scan_ranges[1][1] + include_dist:
                        continue
                gauss = self._gaussian_2d(xy_grid,
                                          amp=amplitudes[i],
                                          pos=positions[i],
                                          sigma=sigmas[i],
                                          theta=thetas[i])
                if len(self._current_scan_axes) == 1:
                    self._scan_image += gauss[:, 0]
                else:
                    self._scan_image += gauss

            if self._constraints.has_position_feedback:
                feedback_axes = tuple(self._constraints.axes.values())
            else:
                feedback_axes = None
            self._scan_data = ScanData(
                channels=tuple(self._constraints.channels.values()),
                scan_axes=tuple(self._constraints.axes[ax] for ax in self._current_scan_axes),
                scan_range=self._current_scan_ranges,
                scan_resolution=self._current_scan_resolution,
                scan_frequency=self._current_scan_frequency,
                position_feedback_axes=feedback_axes,
                target_at_start=self.get_target()
            )

            self._scan_data.new_scan()
            self.__scan_start = time.time()
            self.__last_line = -1
            line_time = self._current_scan_resolution[0] / self._current_scan_frequency
            self.__update_timer.setInterval(int(round(line_time * 1000)))
            self.__start_timer()
            return 0

    def stop_scan(self):
        """ Closes the scanner and cleans up afterwards.

        @return int: error code (0:OK, -1:error)
        """
        with self._thread_lock:
            self.log.debug('Scanning probe dummy "stop_scan" called.')
            if self.module_state() == 'locked':
                self._scan_image = None
                self.module_state.unlock()
            return 0

    def emergency_stop(self):
        """
        """
        try:
            self.module_state.unlock()
        except FysomError:
            pass
        self._scan_image = None
        self.log.warning('Scanner has been emergency stopped.')
        return 0

    def get_scan_data(self):
        """
        @return ScanData: ScanData instance used in the scan
        """
        with self._thread_lock:
            # if self.thread() is not QtCore.QThread.currentThread():
            #     self.log.debug('Scanning probe dummy "get_scan_data" called.')
            if self._scan_data is None:
                self.log.debug('No scan data in hardware, returning None')
                return None

            if self.module_state() != 'idle':
                elapsed = time.time() - self.__scan_start
                line_time = self._current_scan_resolution[0] / self._current_scan_frequency

                if self._scan_data.scan_dimension == 2:
                    acquired_lines = min(int(np.floor(elapsed / line_time)),
                                         self._current_scan_resolution[1])
                    if acquired_lines > 0:
                        if self.__last_line < acquired_lines - 1:
                            if self.__last_line < 0:
                                self.__last_line = 0

                            for ch in self._constraints.channels:
                                tmp = self._scan_image[:, self.__last_line:acquired_lines]
                                self._scan_data.data[ch][:, self.__last_line:acquired_lines] = tmp

                            self.__last_line = acquired_lines - 1
                        if acquired_lines >= self._current_scan_resolution[1]:
                            self.module_state.unlock()
                        elif self.thread() is QtCore.QThread.currentThread():
                            self.__start_timer()
                else:
                    acquired_lines = min(int(np.floor(elapsed / line_time)),
                                         self._current_scan_resolution[0])
                    if acquired_lines > 0:
                        if self.__last_line < 0:
                            self.__last_line = 0
                        if self.__last_line < acquired_lines - 1:
                            if self.__last_line < 0:
                                self.__last_line = 0

                            for ch in self._constraints.channels:
                                tmp = self._scan_image[self.__last_line:acquired_lines]
                                self._scan_data.data[ch][self.__last_line:acquired_lines] = tmp

                            self.__last_line = acquired_lines - 1
                        if acquired_lines >= self._current_scan_resolution[0]:
                            self.module_state.unlock()
                        elif self.thread() is QtCore.QThread.currentThread():
                            self.__start_timer()
            return self._scan_data

    def __start_timer(self):
        if self.thread() is not QtCore.QThread.currentThread():
            QtCore.QMetaObject.invokeMethod(self.__update_timer,
                                            'start',
                                            QtCore.Qt.BlockingQueuedConnection)
        else:
            self.__update_timer.start()

    def __stop_timer(self):
        if self.thread() is not QtCore.QThread.currentThread():
            QtCore.QMetaObject.invokeMethod(self.__update_timer,
                                            'stop',
                                            QtCore.Qt.BlockingQueuedConnection)
        else:
            self.__update_timer.stop()
    def _init_scan_grid(self, x_values, y_values):
        return np.meshgrid(x_values, y_values, indexing='ij')

    @staticmethod
    def _gaussian_2d(xy, amp, pos, sigma, theta=0, offset=0):
        x, y = xy
        sigx, sigy = sigma
        x0, y0 = pos
        a = np.cos(-theta) ** 2 / (2 * sigx ** 2) + np.sin(-theta) ** 2 / (2 * sigy ** 2)
        b = np.sin(2 * -theta) / (4 * sigy ** 2) - np.sin(2 * -theta) / (4 * sigx ** 2)
        c = np.sin(-theta) ** 2 / (2 * sigx ** 2) + np.cos(-theta) ** 2 / (2 * sigy ** 2)
        x_prime = x - x0
        y_prime = y - y0
        return offset + amp * np.exp(
            -(a * x_prime ** 2 + 2 * b * x_prime * y_prime + c * y_prime ** 2))


    # FUNCTIONS FROM HERE ONWARDS ARE FROM OLD QUDI NI CARD HARDWARE FILE
    def _start_analog_output(self):
        """ Starts or restarts the analog output.

        @return int: error code (0:OK, -1:error)
        """
        try:
            # If an analog task is already running, kill that one first
            if self._scanner_ao_task is not None:
                # stop the analog output task
                daq.DAQmxStopTask(self._scanner_ao_task)

                # delete the configuration of the analog output
                daq.DAQmxClearTask(self._scanner_ao_task)

                # set the task handle to None as a safety
                self._scanner_ao_task = None

            # initialize ao channels / task for scanner, should always be active.
            # Define at first the type of the variable as a Task:
            self._scanner_ao_task = daq.TaskHandle()

            # create the actual analog output task on the hardware device. Via
            # byref you pass the pointer of the object to the TaskCreation function:
            daq.DAQmxCreateTask('ScannerAO', daq.byref(self._scanner_ao_task))
            for n, chan in enumerate(self._scanner_ao_channels):
                # Assign and configure the created task to an analog output voltage channel.
                daq.DAQmxCreateAOVoltageChan(
                    # The AO voltage operation function is assigned to this task.
                    self._scanner_ao_task,
                    # use (all) scanner ao_channels for the output
                    chan,
                    # assign a name for that channel
                    'Scanner AO Channel {0}'.format(n),
                    # minimum possible voltage
                    self._scanner_voltage_ranges[n][0],
                    # maximum possible voltage
                    self._scanner_voltage_ranges[n][1],
                    # units is Volt
                    daq.DAQmx_Val_Volts,
                    # empty for future use
                    '')
        except:
            self.log.exception('Error starting analog output task.')
            return -1
        return 0

    def _stop_analog_output(self):
        """ Stops the analog output.

        @return int: error code (0:OK, -1:error)
        """
        if self._scanner_ao_task is None:
            return -1
        retval = 0
        try:
            # stop the analog output task
            daq.DAQmxStopTask(self._scanner_ao_task)
        except:
            self.log.exception('Error stopping analog output.')
            retval = -1
        try:
            daq.DAQmxSetSampTimingType(self._scanner_ao_task, daq.DAQmx_Val_OnDemand)
        except:
            self.log.exception('Error changing analog output mode.')
            retval = -1
        return retval
    def get_voltage(self):
        return self._a_voltage

    def set_voltage(self, v):
        self._a_voltage = v
        return self.scanner_set_position()

    def scanner_set_position(self, x=None, y=None, z=None, a=None):
        """Move stage to x, y, z, a (where a is the fourth voltage channel).

        #FIXME: No volts
        @param float x: postion in x-direction (volts)
        @param float y: postion in y-direction (volts)
        @param float z: postion in z-direction (volts)
        @param float a: postion in a-direction (volts)

        @return int: error code (0:OK, -1:error)
        """

        if self.module_state() == 'locked':
            self.log.error('Another scan_line is already running, close this one first.')
            return -1

        if x is not None:
            if not(self._position_ranges[0][0] <= x <= self._position_ranges[0][1]):
                self.log.error('You want to set x out of range: {0:f}.'.format(x))
                return -1
            self._current_position[0] = np.float(x)

        if y is not None:
            if not(self._position_ranges[1][0] <= y <= self._position_ranges[1][1]):
                self.log.error('You want to set y out of range: {0:f}.'.format(y))
                return -1
            self._current_position[1] = np.float(y)

        if z is not None:
            if not(self._position_ranges[2][0] <= z <= self._position_ranges[2][1]):
                self.log.error('You want to set z out of range: {0:f}.'.format(z))
                return -1
            self._current_position[2] = np.float(z)

        if a is not None:
            if self._a_other:
                self.log.error("Tried to set position on AO channel 'a' whilst 'a' is a voltage output")
                return -1
            elif not(self._position_ranges[3][0] <= a <= self._position_ranges[3][1]):
                self.log.error('You want to set a out of range: {0:f}.'.format(a))
                return -1
            else:
                self._current_position[3] = np.float(a)

        # the position has to be a vstack
        my_position = np.vstack(self._current_position)
        voltages = self._scanner_position_to_volt(my_position)

        # then directly write the position to the hardware
        try:
            self._write_scanner_ao(
                voltages=voltages,
                start=True)
        except:
            return -1
        return 0

    def _scanner_position_to_volt(self, positions=None):
        """ Converts a set of position pixels to acutal voltages.

        @param float[][n] positions: array of n-part tuples defining the pixels

        @return float[][n]: array of n-part tuples of corresponing voltages

        The positions is typically a matrix like
            [[x_values], [y_values], [z_values], [a_values]]
            but x, xy, xyz and xyza are allowed formats.
        """

        if not isinstance(positions, (frozenset, list, set, tuple, np.ndarray, )):
            self.log.error('Given position list is no array type.')
            return np.array([np.NaN])

        vlist = []
        for i, position in enumerate(positions):
            vlist.append(
                (self._scanner_voltage_ranges[i][1] - self._scanner_voltage_ranges[i][0])
                / (self._position_ranges[i][1] - self._position_ranges[i][0])
                * (position - self._position_ranges[i][0])
                + self._scanner_voltage_ranges[i][0]
            )

        if self._a_other:
            vlist.append(np.repeat(self._a_voltage, len(positions[0])))

        volts = np.vstack(vlist)

        for i, v in enumerate(volts):
            if v.min() < self._scanner_voltage_ranges[i][0] or v.max() > self._scanner_voltage_ranges[i][1]:
                self.log.error(
                    'Voltages ({0}, {1}) exceed the limit, the positions have to '
                    'be adjusted to stay in the given range.'.format(v.min(), v.max()))
                return np.array([np.NaN])
        return volts

class NationalInstrumentsXSeries(CoordinateTransformMixin, NationalInstrumentsXSeriesBare):

    def _init_scan_grid(self, x_values, y_values):
        # this is fake transformation, as only 2 coordinates of the scan_grid are taken

        vectors = {'x': x_values, 'y': y_values}
        vectors = self._expand_coordinate(vectors)
        vectors_tilted = self.coordinate_transform(vectors)

        grid = np.meshgrid(vectors_tilted['x'], vectors_tilted['y'], indexing='ij')

        #if self.coordinate_transform_enabled:
        #    self.log.debug(f"Transforming scan grid: {grid}")

        return grid






