from __future__ import annotations
import enum
from typing import Iterable, Optional, SupportsFloat as Numeric, Tuple
import argparse
import time
import numpy as np
import matplotlib.pyplot as plt
import pickle
from xarray import Dataset
from datetime import datetime
import warnings

from pydwf import (DwfLibrary, DwfDevice, AnalogIn, DigitalIn, AnalogOut,
                   DwfEnumConfigInfo, DwfAcquisitionMode, DwfAnalogOutFunction,
                   DwfTriggerSource, DwfAnalogInTriggerType, DwfTriggerSlope,
                   DwfState, DwfAnalogInFilter,
                   DwfDigitalInClockSource, DwfDigitalInSampleMode,
                   PyDwfError)
from pydwf.utilities import openDwfDevice


@enum.unique
class DwfDigitalInTriggerType(enum.Enum):
    Disabled = 0
    Low = 1
    High = 2
    RisingEdge = 3
    FallingEdge = 4


@enum.unique
class DwfMaximizeBuffer(enum.Enum):
    AnalogIn = 0
    DigitalIn = 1


def GetAnalogData(analogIn: AnalogIn, sample_frequency: Numeric, record_length: Numeric, *, channels: Optional[int | Tuple[int]] = None, input_range: Optional[Numeric | Tuple[Numeric]] = None, trigger_channel: Optional[int] = None, trigger_position: Optional[Numeric] = 0.1, trigger_level: Optional[Numeric] = 0, trigger_type=DwfAnalogInTriggerType.Edge, trigger_cond=DwfTriggerSlope.Rise, trigger_retry: Optional[int] = None, trigger_holdoff: Numeric = 500e-6, trigger_hyst: Numeric = 0.05, filter=DwfAnalogInFilter.Average) -> Tuple[bool, Dataset]:
    """Get analog data from the AnalogIn instrument.

    Args:
        analogIn (AnalogIn): Analog Input Device.
        sample_frequency (Numeric): Sampling frequency in Hz.
        record_length (Numeric): Recording length in seconds.
        channels (int | Tuple[int], optional): Channels to get measurements from. Availabe channels are 0 and 1. Multi-channel measurements can be requested by sending tuple([0, 1]). Defaults to None, which implies both channels.
        input_range (Numeric | Tuple[Numeric], optional): Input range of the channel(s). Defaults to None, setting both channels to 5Vpp.
        trigger_channel (int, optional): Which channel to trigger on. Defaults to None.
        trigger_position (Numeric, optional): Fraction of recording length where trigger position is set. e.g. trigger_position=-0.5 would set the trigger position halfway the capture window. Defaults to -0.5.
        trigger_level (Numeric, optional): Trigger voltage level. Defaults to 0.
        trigger_type (DwfAnalogInTriggerType, optional): Trigger type (edge or level). Defaults to DwfAnalogInTriggerType.Edge.
        trigger_cond (DwfTriggerSlope, optional): Rising or falling edge, high or low level. Defaults to DwfTriggerSlope.Rise.
        trigger_retry (Optional[Numeric], optional): Number of seconds to wait for trigger before acquisition is started in case trigger is not detected. Defaults to None, in which case waits for 1 second. Set to negative value for infinite retries, must not be 0.
        trigger_holdoff (Numeric, optional): Trigger holdoff time in seconds. A second trigger within this timeframe is ignored. Defaults to 500e-6.
        trigger_hyst (Numeric, optional): Trigger hysteresis in Volts. Defaults to 0.05.
        filter (DwfAnalogInFilter, optional): Data filtering for the ADC. Defaults to DwfAnalogInFilter.Average.

    Raises:
        ValueError: Invalid channel index.
        ValueError: Invalid input range.
        ValueError: Number of channels and number of input range parameters do not match.

    Returns:
        Tuple[bool, Dataset]: Valid status and Dataset containing the data.
    """
    trigger_flag = False
    if trigger_channel is not None and trigger_channel in (0, 1):
        trigger_flag = True

    if trigger_retry is None:
        trigger_retry = 1
    if trigger_retry == 0:
        raise ValueError(
            "Trigger retry must be greater than 0, or None, or negative for infinite retries")
    if trigger_retry < 0:
        trigger_retry = None

    if trigger_position is None:
        trigger_position = 0.1
    if trigger_position > 0:
        trigger_position = -trigger_position
    if not -1 <= trigger_position <= 0:
        raise ValueError("Trigger position must be between 0 and 1")
    trigger_position = trigger_position * record_length

    if trigger_flag and trigger_level is None:
        trigger_level = 0.0  # 0 volts by default

    # Configure analog input instrument acquisition.

    CH1 = 0
    CH2 = 1

    if channels is None:
        channels = (CH1, CH2)
    elif isinstance(channels, int):
        if channels not in (CH1, CH2):
            raise ValueError("Channel index must be 0 or 1.")
        channels = (channels,)
    elif isinstance(channels, tuple):
        for channel_index in channels:
            if channel_index not in (CH1, CH2):
                raise ValueError("Channel index must be 0 or 1.")

    inp_min, inp_max, _ = analogIn.channelRangeInfo()

    if input_range is None:
        input_range = np.ones(len(channels)) * 5
    elif isinstance(input_range, Numeric):
        input_range = (input_range,)
    for i in input_range:
        if not inp_min <= i <= inp_max:
            raise ValueError(
                f"Input range must be between [{inp_min}V, {inp_max}V]")
    if len(input_range) != len(channels):
        raise ValueError(
            "Number of input ranges must match number of channels")

    for channel_index, range_index in zip(channels, input_range):
        analogIn.channelEnableSet(channel_index, True)
        analogIn.channelFilterSet(channel_index, filter)
        analogIn.channelRangeSet(channel_index, range_index)

    analogIn.acquisitionModeSet(DwfAcquisitionMode.Record)
    analogIn.frequencySet(sample_frequency)
    analogIn.recordLengthSet(record_length)

    if trigger_flag:
        # Set up trigger for the analog input instrument.
        # We will trigger on the rising transitions of CH2 (the "cosine" channel) through 0V.
        # print("Setting up trigger on channel {}.".format(trigger_channel))
        analogIn.triggerSourceSet(DwfTriggerSource.DetectorAnalogIn)
        analogIn.triggerChannelSet(trigger_channel)
        analogIn.triggerTypeSet(trigger_type)
        analogIn.triggerConditionSet(trigger_cond)
        analogIn.triggerPositionSet(trigger_position)
        analogIn.triggerLevelSet(trigger_level)
        analogIn.triggerHysteresisSet(trigger_hyst)
        # A small amount of hysteresis to make sure we only see rising edges.
        analogIn.triggerHoldOffSet(trigger_holdoff)

    # Calculate number of samples for each acquisition.
    num_samples = round(sample_frequency * record_length)

    # print("Recording {} samples ...".format(num_samples))

    # Inner loop: single acquisition, receive data from AnalogIn instrument and display it.

    samples = []

    total_samples = total_samples_lost = total_samples_corrupted = 0

    analogIn.configure(True, False)  # Apply configuration.

    while analogIn.status(False) != DwfState.Ready:
        pass  # Wait for ready

    analogIn.configure(False, True)  # Start acquisition sequence.

    try:
        while True:
            status = analogIn.status(True)
            (current_samples_available, current_samples_lost,
             current_samples_corrupted) = analogIn.statusRecord()

            if status == DwfState.Triggered:
                triggered = True

            if not trigger_flag and triggered:
                total_samples += current_samples_available

            if trigger_flag and trigger_retry is not None and not triggered:
                if trigger_retry <= 0:
                    raise RuntimeError("Failed to trigger")
                elif trigger_retry > 0:
                    trigger_retry -= current_samples_available + current_samples_lost

            total_samples_lost += current_samples_lost
            total_samples_corrupted += current_samples_corrupted

            if current_samples_lost != 0:
                # Append NaN samples as placeholders for lost samples.
                # This follows the Digilent example.
                # We haven't verified yet that this is the proper way to handle lost samples.
                lost_samples = np.full(
                    (current_samples_lost, len(channels)), np.nan)
                samples.append(lost_samples)

            if current_samples_available != 0:
                # Append samples read from both channels.
                # Note that we read the samples separately for each channel;
                # We then put them into the same 2D array with shape (current_samples_available, 2).
                current_samples = np.vstack([analogIn.statusData(channel_index, current_samples_available)
                                            for channel_index in channels]).transpose()
                samples.append(current_samples)

            if status == DwfState.Done:
                # We received the last of the record samples.
                # Note the time, in seconds, of the first valid sample, and break from the acquisition loop.
                if trigger_flag:
                    time_of_first_sample = analogIn.triggerPositionStatus()
                else:
                    time_of_first_sample = 0.0
                if total_samples < num_samples:
                    warnings.warn("WARNING - Collected {}/{} samples only!".format(
                        total_samples, num_samples), RuntimeWarning)
                break
    except (Exception, KeyboardInterrupt) as e:  # Stop capture on error
        analogIn.reset()
        samples = [np.empty((0, len(channels)), dtype=np.float64)]

    if total_samples_lost != 0:
        warnings.warn("WARNING - {} samples were lost! Reduce sample frequency.".format(
            total_samples_lost), RuntimeWarning)

    if total_samples_corrupted != 0:
        warnings.warn("WARNING - {} samples could be corrupted! Reduce sample frequency.".format(
            total_samples_corrupted), RuntimeWarning)

    # Concatenate all acquired samples. The result is an (n, 2) array of sample values.
    try:
        samples = np.concatenate(samples)
    except ValueError as ex:
        pickle.dump(samples, open(
            f"{datetime.now().strftime('%Y%m%d%H%M%S')}.pkl", "wb"))
        raise ex

    # Calculate sample time of each of the samples.
    t = time_of_first_sample + np.arange(len(samples)) / sample_frequency

    data_vars = {}
    for channel_index in channels:
        data_vars[f"ch{channel_index}"] = (("time"), samples[:, channel_index])
    coords = {
        "time": (('time'), t, {'units': 's', 'long_name': 'Time'}),
    }

    ds = Dataset(
        data_vars,
        coords,
        attrs={
            "sample_frequency": sample_frequency,
            "triggered": int(triggered),
            "total_samples": total_samples,
            "lost_samples": total_samples_lost,
            "corrupted_samples": total_samples_corrupted,
        })

    status = True & (total_samples_lost == 0) & (total_samples_corrupted == 0)

    return status, ds


def GetDigitalData(digitalIn: DigitalIn, sample_frequency: Numeric, record_length: Numeric, *, channels: Optional[int | Iterable[int]] = None, trigger: Optional[DwfDigitalInTriggerType | Iterable[DwfDigitalInTriggerType]] = None, trigger_position: Optional[Numeric] = 0.1, buffer_size: Optional[int] = None, trigger_retry: Optional[Numeric] = None) -> Tuple[bool, Dataset]:
    """Collect digital data samples from the DigitalIn instrument.

    Args:
        digitalIn (DigitalIn): Digital Input Device.
        sample_frequency (Numeric): Digital sampling frequency in Hz.
        record_length (Numeric): Length of recording in seconds.
        channels (Optional[int  |  Iterable[int]], optional): Input channels. Defaults to None, in which case all channels are used.
        trigger (Optional[DwfDigitalInTriggerType  |  Iterable[DwfDigitalInTriggerType]], optional): Trigger type selection. Defaults to None. In case no channels are specified, the trigger applies to all channels.
        trigger_position (Optional[Numeric], optional): Position of trigger in the recording window. Must be a value between 0 and 1. Setting the value to 0.5 sets the trigger position at the middle of the recording window. Defaults to 0.1.
        buffer_size (Optional[int], optional): Device buffer size. Defaults to None.
        trigger_retry (Optional[Numeric], optional): Number of seconds to wait for trigger before acquisition is started in case trigger is not detected. Defaults to None, in which case waits for 1 second. Set to negative value for infinite retries, must not be 0.

    Raises:
        ValueError: Number of triggers does not match number of channels.
        ValueError: Trigger position must be between 0 and 1.
        ValueError: Trigger retry must be greater than 0, or None, or negative for infinite retries.
        ValueError: Sample frequency too low.
        ValueError: Sample frequency too high.
        IOError: Failed to set sample frequency.
        ValueError: Invalid trigger type.
        RuntimeError: Failed to trigger.

    Returns:
        Tuple[bool, Dataset]: Valid status and Dataset containing the data.
    """
    if isinstance(channels, int):
        channels = (channels,)
    if trigger is None:
        trigger = DwfDigitalInTriggerType.Disabled
    if not isinstance(trigger, Iterable) and channels is not None:
        trigger = tuple([trigger]*len(channels))
    if channels is not None and len(trigger) != len(channels):
        raise ValueError("Number of triggers must match number of channels")
    if trigger_position is None:  # Set trigger position to 10% of record length
        trigger_position = 0.1
    if trigger_position > 0:
        trigger_position = -trigger_position
    if not -1 <= trigger_position <= 0:
        raise ValueError("Trigger position must be between 0 and 1")
    if trigger_retry is None:
        trigger_retry = 1
    if trigger_retry == 0:
        raise ValueError(
            "Trigger retry must be greater than 0, or None, or negative for infinite retries")
    if trigger_retry < 0:
        trigger_retry = None

    # Set up sample frequency
    clk_freq = digitalIn.internalClockInfo()  # Get internal clock frequency
    max_clkdiv = digitalIn.dividerInfo()  # Get maximum clkdiv
    clkdiv = int(clk_freq / sample_frequency)  # Calculate clkdiv
    if clkdiv > max_clkdiv:
        raise ValueError(
            "Sample frequency too low, minimum is %d Hz" % (clk_freq / max_clkdiv))
    if clkdiv < 1:
        raise ValueError(
            "Sample frequency too high, maximum is %d Hz" % (clk_freq))
    digitalIn.dividerSet(clkdiv)  # Set clkdiv
    sample_frequency = clk_freq // clkdiv  # Get actual sample frequency
    if digitalIn.dividerGet() != clkdiv:
        raise IOError("Failed to set sample frequency")

    if trigger_retry is not None:
        # Convert trigger retry to number of samples
        trigger_retry = int(trigger_retry * sample_frequency)

    # Set up record length
    # Convert record length to number of samples
    num_samples = int(record_length * sample_frequency)

    digitalIn.sampleModeSet(DwfDigitalInSampleMode.Simple)
    digitalIn.acquisitionModeSet(DwfAcquisitionMode.Record)
    if buffer_size is None:
        buffer_size = digitalIn.bufferSizeInfo()
    digitalIn.bufferSizeSet(buffer_size)
    digitalIn.triggerSourceSet(DwfTriggerSource.DetectorDigitalIn)
    digitalIn.triggerPrefillSet(-int(trigger_position * num_samples))

    # set up trigger
    level_low = 0x0
    level_high = 0x0
    edge_rise = 0x0
    edge_fall = 0x0

    if channels is not None:
        for channel_index, trigger_type in zip(channels, trigger):
            if trigger_type == DwfDigitalInTriggerType.Disabled:
                pass
            elif trigger_type == DwfDigitalInTriggerType.Low:
                level_low |= 1 << channel_index
            elif trigger_type == DwfDigitalInTriggerType.High:
                level_high |= 1 << channel_index
            elif trigger_type == DwfDigitalInTriggerType.RisingEdge:
                edge_rise |= 1 << channel_index
            elif trigger_type == DwfDigitalInTriggerType.FallingEdge:
                edge_fall |= 1 << channel_index
            else:
                raise ValueError("Invalid trigger type")

    trig_any = level_low | level_high | edge_rise | edge_fall

    digitalIn.triggerSet(level_low, level_high, edge_rise, edge_fall)

    digitalIn.configure(True, False)

    while digitalIn.status(False) != DwfState.Ready:
        pass  # Wait for ready

    samp_format = digitalIn.sampleFormatGet()

    if channels is None and trigger is not None:  # If no channels are specified, trigger on all channels
        channels = tuple(range(samp_format))
        for channel_index in channels:
            if trigger == DwfDigitalInTriggerType.Disabled:
                pass
            elif trigger == DwfDigitalInTriggerType.Low:
                level_low |= 1 << channel_index
            elif trigger == DwfDigitalInTriggerType.High:
                level_high |= 1 << channel_index
            elif trigger == DwfDigitalInTriggerType.RisingEdge:
                edge_rise |= 1 << channel_index
            elif trigger == DwfDigitalInTriggerType.FallingEdge:
                edge_fall |= 1 << channel_index
            else:
                raise ValueError("Invalid trigger type")
        trig_any = level_low | level_high | edge_rise | edge_fall

        digitalIn.triggerSet(level_low, level_high, edge_rise, edge_fall)

        digitalIn.configure(True, False)

        while digitalIn.status(False) != DwfState.Ready:
            pass  # Wait for ready

    digitalIn.configure(False, True)

    total_samples = total_samples_lost = total_samples_corrupted = 0
    samples = []
    triggered = False
    try:
        while True:
            status = digitalIn.status(True)
            (current_samples_available, current_samples_lost,
             current_samples_corrupted) = digitalIn.statusRecord()

            if status == DwfState.Triggered:
                triggered = True

            if not trig_any and triggered:
                total_samples += current_samples_available

            if trig_any and trigger_retry is not None and not triggered:
                if trigger_retry <= 0:
                    raise RuntimeError("Failed to trigger")
                elif trigger_retry > 0:
                    trigger_retry -= current_samples_available + current_samples_lost

            total_samples_lost += current_samples_lost
            total_samples_corrupted += current_samples_corrupted

            if current_samples_lost != 0:
                # Append NaN samples as placeholders for lost samples.
                # This follows the Digilent example.
                # We haven't verified yet that this is the proper way to handle lost samples.
                lost_samples = np.full((current_samples_lost), np.nan)
                samples.append(lost_samples)

            if current_samples_available != 0:
                # Append samples read
                current_samples = digitalIn.statusData(
                    current_samples_available)
                samples.append(current_samples)

            if status == DwfState.Done or total_samples > num_samples:
                # We received the last of the record samples.
                # Note the time, in seconds, of the first valid sample, and break from the acquisition loop.
                if total_samples < num_samples:
                    warnings.warn("WARNING - Collected {}/{} samples only!".format(
                        total_samples, num_samples), RuntimeWarning)
                break
    except (Exception, KeyboardInterrupt) as e:  # Stop capture on error
        print(e)
        digitalIn.reset()
        samples = [np.empty(0, dtype=np.uint32)]

    if total_samples_lost != 0:
        warnings.warn("WARNING - {} samples were lost! Reduce sample frequency.".format(
            total_samples_lost), RuntimeWarning)
        # Discard all samples on error so that NaNs don't cause problems: You probably want to retry anyway
        samples = [np.empty(0, dtype=np.uint32)]

    if total_samples_corrupted != 0:
        warnings.warn("WARNING - {} samples could be corrupted! Reduce sample frequency.".format(
            total_samples_corrupted), RuntimeWarning)
        # Discard all samples on error because time should be discontinuous: You probably want to retry anyway
        samples = [np.empty(0, dtype=np.uint32)]

    samples = np.concatenate(samples)

    if channels is None:
        channels = tuple(range(samp_format))

    data_vars = {}
    for channel_index in channels:
        data_vars[f"ch{channel_index}"] = (
            ("time"), samples & (1 << channel_index) != 0)
    coords = {
        "time": (('time'), np.arange(len(samples)) / sample_frequency, {'units': 's', 'long_name': 'Time'}),
    }
    ds = Dataset(
        data_vars,
        coords,
        attrs={
            "sample_frequency": sample_frequency,
            "triggered": int(triggered),
            "total_samples": total_samples,
            "lost_samples": total_samples_lost,
            "corrupted_samples": total_samples_corrupted,
        })

    status = True & (total_samples_lost == 0) & (total_samples_corrupted == 0)

    return status, ds


def openAD2(serial_number_filter=None, buffer_maximize: DwfMaximizeBuffer = DwfMaximizeBuffer.AnalogIn) -> DwfDevice:
    """Open an Analog Discovery 2 device.

    If multiple devices are connected, the one with the highest analog in buffer size is selected.

    Args:
        serial_number_filter (str, optional): If specified, only devices with a matching serial number are considered. Defaults to None.

    Returns:
        pydwf.core.DwfDevice: The opened device.

    Raises:
        PyDwfError: An error occurred while opening the device.
    """
    dwf = DwfLibrary()

    def maximize_analog_in_buffer_size(configuration_parameters):
        """Select the configuration with the highest possible analog in buffer size."""
        return configuration_parameters[DwfEnumConfigInfo.AnalogInBufferSize]

    def maximize_digital_in_buffer_size(configuration_parameters):
        """Select the configuration with the highest possible digital in buffer size."""
        return configuration_parameters[DwfEnumConfigInfo.DigitalInBufferSize]

    if buffer_maximize == DwfMaximizeBuffer.AnalogIn:
        score_func = maximize_analog_in_buffer_size
    elif buffer_maximize == DwfMaximizeBuffer.DigitalIn:
        score_func = maximize_digital_in_buffer_size
    else:
        raise ValueError("Invalid buffer maximize mode")

    try:
        device = openDwfDevice(dwf, serial_number_filter=serial_number_filter,
                               score_func=score_func)
        return device
    except PyDwfError as exception:
        print("PyDwfError:", exception)
        raise exception


def main():
    """Parse arguments and start demo."""
    import sys

    parser = argparse.ArgumentParser(
        description="Demonstrate analog input recording with triggering.")

    DEFAULT_SAMPLE_FREQUENCY = 1e6
    DEFAULT_RECORD_LENGTH = 10

    parser.add_argument(
        "-sn", "--serial-number-filter",
        type=str,
        nargs='?',
        dest="serial_number_filter",
        help="serial number filter to select a specific Digilent Waveforms device"
    )

    parser.add_argument(
        "-fs", "--sample-frequency",
        type=float,
        default=DEFAULT_SAMPLE_FREQUENCY,
        help="sample frequency, in samples per second (default: {} Hz)".format(
            DEFAULT_SAMPLE_FREQUENCY)
    )

    parser.add_argument(
        "-r", "--record-length",
        type=float,
        default=DEFAULT_RECORD_LENGTH,
        help="record length, in seconds (default: {} s)".format(
            DEFAULT_RECORD_LENGTH)
    )

    parser.add_argument(
        "-x", "--disable-trigger",
        action="store_false",
        dest="trigger",
        help="disable triggering (default: enabled)"
    )

    args = parser.parse_args()

    with openAD2(serial_number_filter=args.serial_number_filter) as device:
        status, ds = GetAnalogData(device.analogIn,
                                   args.sample_frequency,
                                   args.record_length)

        for idx, key in enumerate(ds.data_vars.keys()):
            print(
                f'{key}: {np.mean(ds[key].values)}, {np.std(ds[key].values)}')
            plt.plot(ds.time.values[:200]*1e6, ds[key].values[:200]*(idx + 1))
        plt.show()

    with openAD2(serial_number_filter=args.serial_number_filter, buffer_maximize=DwfMaximizeBuffer.DigitalIn) as device:
        status, ds = GetDigitalData(device.digitalIn,
                                    args.sample_frequency,
                                    args.record_length,
                                    channels=None,
                                    trigger=None,
                                    trigger_position=0.1,
                                    trigger_retry=None)

        print('Samples:', len(ds.ch0.values))

        for idx, key in enumerate(ds.data_vars.keys()):
            print(
                f'{key}: {np.mean(ds[key].values)}, {np.std(ds[key].values)}')
            plt.plot(ds.time.values[:200]*1e6, ds[key].values[:200]*(idx + 1))
        plt.show()

        print('Corrupted samples: ', ds.attrs['corrupted_samples'])
        print('Lost samples: ', ds.attrs['lost_samples'])


if __name__ == "__main__":
    main()
