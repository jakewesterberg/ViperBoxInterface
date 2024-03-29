from typing import List, Optional, Type, Any, Tuple

import NeuraviperPy as NVP
import threading
import time
import numpy as np
import socket
import logging
import ctypes
from pathlib import Path
from parameters import (
    ConfigurationParameters,
    PulseShapeParameters,
    PulseTrainParameters,
    ViperBoxConfiguration,
    StimulationSweepParameters,
)

# import sys

# logging.basicConfig(level=logging.INFO)
# logging.basicConfig(stream=sys.stdout, level=logging.DEBUG)
logger = logging.getLogger(__name__)
# formatter = logging.Formatter('%(levelname)-8s %(asctime)s
# - %(name)s - %(message)s', '%H:%M:%S')
# file_handler.setFormatter(formatter)
# logger.addHandler(file_handler)


class ViperBoxControl:
    """
    Controller class for handling recordings from the ViperBox device.
    """

    BUFFER_SIZE = 500
    SKIP_SIZE = 20
    FREQ = 20000
    OS_WRITE_TIME = 1

    def __init__(
        self,
        # recording_file_name: str = "",
        probe: int = 0,
        config_params: Optional[ConfigurationParameters] = None,
        stim_unit: int = 0,
        recording_file_folder: str = Path.cwd(),
        metadata_stream: Optional[List[Any]] = None,
        no_box: bool = False,
        emulated: bool = False,
    ) -> None:
        """Initializes the ViperBoxControl object."""
        # TODO: check which other parameters logically are part of self and init.
        logger.info("Instantiating ViperBoxControl")
        self._recording = False
        # self._recording_file_name: str = (
        #     recording_file_name + time.strftime("_%Y%m%d_%H%M%S") + ".bin"
        # )
        self._recording_file_folder = recording_file_folder
        self._metadata_stream: Optional[List[Any]] = metadata_stream
        self._probe = probe
        self._stim_unit = stim_unit
        self.config_params = config_params
        self._handle: Type[Any] = None
        self._connected_handle: bool = False
        self._connected_BS: bool = False
        self._connected_probe: bool = False
        self.emulated: bool = emulated

        if no_box:
            self._handle = "no_box"
        else:
            if self.connect_viperbox():
                logger.info("ViperBox set up completed successfully")
            else:
                logger.warning("ViperBox instantiation failed")

        NVP.setLogLevel(NVP.LogLevel.VERBOSE)

    def disconnect_viperbox(self):
        NVP.setFileStream(self._handle, "")
        NVP.closeBS(self._handle)
        self._connected_BS = False
        self._connected_probe = False
        NVP.destroyHandle(self._handle)
        self._connected_handle = False

    def connect_viperbox(self):
        if self._handle == "no_box":
            return True
        if not self._connect_handle():
            return False
        if not self._connect_BS():
            return False
        self._set_emulation()
        if not self._connect_probe():
            return False
        return True

    def check_connection(self):
        if not self._connected_handle:
            self._connected_handle = False
        if not self._connected_BS:
            self._connected_BS = False
        if not self._connected_probe:
            self._connected_probe = False
        return (self._connected_handle, self._connected_BS, self._connected_probe)

    def _connect_handle(self):
        if not self._connected_handle:
            try:
                self._handle = NVP.createHandle(0)
                self._connected_handle = True
                logger.info("Handle created successfully")
                return True
            except Exception:
                logger.error("Error while setting up handle.", exc_info=True)
                return False
        return False

    def _connect_BS(self):
        if not self._connected_BS and self._connected_handle:
            try:
                NVP.openBS(self._handle)
                self._connected_BS = True
                logger.info("Base station set up successfully")
                return True
            except Exception as e:
                logger.error(f"Error while setting up BS: {e}")
                return False
        return False

    def _connect_probe(self):
        if not self._connected_probe and self._connected_BS and self._connected_handle:
            logger.info("Connecting probe")
            try:
                NVP.openProbes(self._handle)
                NVP.init(self._handle, self._probe)
                self._connected_probe = True
                logger.info("Probe connected and initialized successfully")
                return True
            except Exception as e:
                logger.error(f"Error while setting up probe: {e}")
                return False
        return False

    def _set_emulation(self):
        if self._connect_handle:
            if self.emulated:
                NVP.setDeviceEmulatorMode(self._handle, NVP.DeviceEmulatorMode.LINEAR)
                NVP.setDeviceEmulatorType(
                    self._handle, NVP.DeviceEmulatorType.EMULATED_PROBE
                )
                logger.info("Device emulation switched on.")
                return True
            else:
                NVP.setDeviceEmulatorMode(self._handle, NVP.DeviceEmulatorMode.OFF)
                NVP.setDeviceEmulatorType(self._handle, NVP.DeviceEmulatorType.OFF)
                logger.info("Device emulation switched off.")
                return True
        logger.warning("No handle found while trying to set emulation type.")
        return False

    def update_config(self, config_params: ConfigurationParameters) -> bool:
        self.config_params = config_params
        return True

    def set_file_path(self, folder_path, file_name):
        self._recording_file_folder = folder_path
        self._recording_file_name = file_name + time.strftime("_%Y%m%d_%H%M%S") + ".bin"
        return True

    @property
    def _recording_path(self) -> Optional[str]:
        """Return the combined path of the recording file location and name."""
        if self._recording_file_name and self._recording_file_folder:
            return Path(self._recording_file_folder) / self._recording_file_name
        return None

    @staticmethod
    def _currentTime() -> float:
        """Return the current time in seconds since the epoch."""
        return time.time_ns() / (10**9)

    def control_rec_setup(
        self,
        reference_electrode: Optional[int] = 0,
        electrode_mapping: Optional[bytes] = None,
        metadata_stream: Optional[List[Any]] = None,
    ) -> bool:
        """
        Handles setting recording parameters.

        :param reference_electrode: (Optional) Reference electrode number.
        :param electrode_mapping: (Optional) Electrode mapping as bytes.
        :param metadata_stream: (Optional) Metadata stream.
        :param emulated: (Optional) Flag to set the device up in emulation mode.

        :return: True if setup was successful, False otherwise.
        """

        if self._handle == "no_box":
            logger.info("Running without ViperBox connected")
            return True

        if self.check_connection() != (True, True, True):
            try:
                self.connect_viperbox()
            except Exception as e:
                print(e)
                logger.error(
                    "To set up a recording, fix the connection with the ViperBox"
                )
            return False

        if not reference_electrode:
            if not (0 <= reference_electrode <= 8):
                raise ValueError(
                    "Error: Invalid reference electrode. "
                    + "Expected a value between 0 and 8."
                )

        self._metadata_stream = metadata_stream

        # Uncommented and included the setup as needed:
        if electrode_mapping:
            for channel, electrode in enumerate(electrode_mapping):
                NVP.selectElectrode(self._handle, self._probe, channel, electrode)

            # NVP.setReference(self._handle, self._probe, 0, reference_electrode)
            # (which reference electrodes?)
            NVP.writeChannelConfiguration(self._handle, self._probe)

        return True

    def combine(self, metadata_stream: List[Any]) -> None:
        """
        Placeholder method for processing metadata stream.

        :param metadata_stream: Metadata stream to process.
        """
        pass

    def send_data_to_socket(self) -> None:
        """Send data packets to a UDP socket, such that Open Ephys and other systems
        can receive the raw data."""

        bufferInterval: float = self.BUFFER_SIZE / self.FREQ

        serverAddressPort: Tuple[str, int] = ("127.0.0.1", 9001)
        MULTICAST_TTL = 2
        UDPClientSocket: socket.socket = socket.socket(
            socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP
        )

        UDPClientSocket.setsockopt(
            socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, MULTICAST_TTL
        )
        time.sleep(0.5)
        self._read_handle = NVP.streamOpenFile(self._recording_file_name, self._probe)

        # status = NVP.readDiagStats(self._handle)
        # skip_packages = status.session_mismatch
        # print('skip_packages: ', skip_packages)
        # dump_count = 0
        # while dump_count < skip_packages:
        #     _ = NVP.streamReadData(self._read_handle, self.SKIP_SIZE)
        #     dump_count += self.SKIP_SIZE
        # print('dump_count: ', dump_count)

        logger.info("Started sending data to Open Ephys")
        while True:
            t1 = self._currentTime()

            packets = NVP.streamReadData(self._read_handle, self.BUFFER_SIZE)
            count = len(packets)
            # print('len(packets): ',len(packets))

            if count < self.BUFFER_SIZE:
                # logger.warning("Out of packets")
                break

            databuffer = np.asarray(
                [packets[i].data for i in range(self.BUFFER_SIZE)], dtype="uint16"
            ).T
            databuffer = databuffer.copy(order="C")
            UDPClientSocket.sendto(databuffer, serverAddressPort)

            t2 = self._currentTime()
            while (t2 - t1) < bufferInterval:
                t2 = self._currentTime()

        NVP.streamClose(self._read_handle)

    def control_rec_start(
        self,
        # recording_file_name: str = 'Recording',
        recording_time: int = 0,
        store_NWB: bool = False,
    ) -> None:
        """
        Handles starting of recording state.

        :param int recording_time: (Optional) Time in seconds that a recording will
        take, will continue indefinitely when set to 0 (default: 0)
        :param bool store_NWB: (Optional) Flag to determine if data should be stored
        as NWB.
        """

        if self._handle == "no_box":
            return True

        # self.set_file_path(self._recording_file_folder, recording_file_name)

        NVP.setFileStream(self._handle, str(self._recording_path))
        NVP.enableFileStream(self._handle, True)

        NVP.arm(self._handle)

        if self._recording:
            logger.info(
                f"Already recording under the name: {self._recording_file_name}"
            )
            return True

        if store_NWB:
            threading.Thread(target=self.combine, args=(self._metadata_stream,)).start()

        NVP.setSWTrigger(self._handle)
        self._recording = True
        logger.info(f"Started recording: {self._recording_file_name}")
        threading.Thread(target=self.send_data_to_socket).start()
        if recording_time:
            time.sleep(recording_time)
            self.control_rec_stop()

    def stimulation_trigger(self, recording_time=0) -> None:
        """Handles start of stimulation."""
        if self._recording is False:
            if recording_time:
                recording_time += 0.5
            self.control_rec_start(recording_time=recording_time)
            # sleep to be able to gather some data before stimulation is started.
            time.sleep(0.5)
        NVP.SUtrig1(self._handle, self._probe, bytes([8]))

    def control_rec_stop(self) -> None:
        """Handles stopping of recording state."""

        if self._handle == "no_box":
            return True

        if not self._recording:
            logger.info("No recording in progress.")
            return True

        NVP.arm(self._handle)
        NVP.setFileStream(self._handle, "")
        self._recording = False
        logger.info(f"Stopped recording: {self._recording_file_name}")
        self._recording_file_name = None

    def control_rec_status(self) -> bool:
        """
        Check the recording status.

        :return: True if currently recording, False otherwise.
        """
        return self._recording

    def __str__(self) -> str:
        """
        Return a string representation of the recording status and name.

        :return: Status of recording and name of the recording file.
        """

        status = "Recording" if self._recording else "Not Recording"
        return f"Status: {status}, Recording Name: {self._recording_file_name}"

    def control_send_parameters(
        self,
        asdf=[],
        # polarity: int = 0,
    ) -> None:
        """Handles setup of stimulation. Sends parameters to the ASIC."""

        self.write_SU()

        print("asdf: ", asdf)
        print("encode_electrodes(): ", encode_electrodes([1, 2, 3]))
        # enable all OSes and connects them to SU 0
        if not asdf:
            osdata = convert_osdata(bytes(64 * [8]))
        else:
            print("electrode list: ", asdf)
            osdata = encode_electrodes(asdf)
        print("komt ie dan...")
        NVP.setOSimage(self._handle, self._probe, convert_osdata(osdata))
        print("en de volgende: ...")
        NVP.writeOSConfiguration(self._handle, self._probe, False)
        print("klaar")

    def stim_sweep(
        self,
        # polarity: int = 0,
        # config_params: ConfigurationParameters = None,
    ) -> None:
        # self.config_params = config_params

        self.config_params.pulse_shape_parameters.pulse_amplitude_equal = True

        self.control_send_parameters(asdf=(ctypes.c_byte * 128)())
        # # prep and SU config
        # self.write_SU()
        # # prep and write OS config
        # NVP.setOSimage(self._handle, self._probe, (ctypes.c_byte * 128)())
        # NVP.writeOSConfiguration(self._handle, self._probe, False)

        if self._recording is False:
            self.control_rec_start(recording_time=0)
            time.sleep(0.5)

        last_stim = (None, None)
        for stimpair in self.config_params.stim_configuration.stim_list:
            if last_stim[0] is not None:
                NVP.setOSEnable(self._handle, self._probe, last_stim[0], False)
            NVP.setOSEnable(self._handle, self._probe, stimpair[0], True)
            # TODO: potentially check if the values are written
            NVP.writeOSConfiguration(self._handle, self._probe, False)
            self.config_params.pulse_shape_parameters.pulse_amplitude_anode = stimpair[
                1
            ]
            self.write_SU()
            # wait until everything is written to ASIC
            time.sleep(self.OS_WRITE_TIME)
            NVP.SUtrig1(self._handle, self._probe, bytes([8]))
            # wait until stimulation is done plus 1 second
            time.sleep(self.config_params.stim_time + 1)
            last_stim = stimpair
        # wait 10 seconds after end of stimulation
        time.sleep(10)
        self.control_rec_stop()

    def write_SU(
        self,
        # config_params: ConfigurationParameters,
        polarity: int = 0,
    ) -> bool:
        # Configure SU 0 and check if SU config was updated.
        # NVP.transferSPI(self._handle, self._probe, 0x00)

        # self.config_params = config_params
        NVP.writeSUConfiguration(
            *self.config_params.get_SUConfig_pars(
                self._handle, self._probe, self._stim_unit, polarity
            )
        )


def encode_electrodes(stim_electrodes) -> str:
    """
    Convert a list of selected electrodes to a binary string representation.

    :param stim_electrodes: List of 0-based electrode indices that are ON.
    :param num_electrodes: Total number of electrodes.
    :return: Binary string representation.
    """
    hex_list = []
    num_electrodes: int = 64
    print("stim_electrodes: ", stim_electrodes)
    for i in range(num_electrodes):
        if i + 1 in stim_electrodes:
            # If the electrode is ON, the representation is '1' followed by '111'
            hex_list.append(8)

        else:
            # If the electrode is OFF, the representation is '0000'
            hex_list.append(0)
    return bytes(hex_list)


def convert_osdata(osdata):
    return (ctypes.c_ubyte * len(osdata)).from_buffer_copy(osdata)


if __name__ == "__main__":
    # Example usage:
    pulse_shape = PulseShapeParameters()
    pulse_train = PulseTrainParameters()
    electrodes = [1, 2, 3]
    viperbox = ViperBoxConfiguration(0)
    stim_configuration = StimulationSweepParameters(
        # stim_electrode_list=[1, 2],
        # rec_electrodes_list=[3, 4],
        # pulse_amplitudes=(1, 10, 2),
        # randomize=True,
        # repetitions=2,
    )
    config = ConfigurationParameters(
        pulse_shape, pulse_train, viperbox, stim_configuration, electrodes
    )

    # controller = ViperBoxControl("test", 0, config, no_box=True)
    controller = ViperBoxControl("test", config_params=config, emulated=False)
    print("viperboxcontrol instantiated, setup recording")
    # controller.connect_viperbox()
    # print('viperbox connected')
    controller.control_rec_setup()
    print("recording set up, starting recording")
    controller.control_send_parameters([1, 2, 3, 6])
    controller.control_rec_start(2)
    print("recording finished, disconnecting")
    # time.sleep(5)
    # controller.disconnect_viperbox()
    # print('viperbox disconnected')
    # print(config.get_SUConfig_pars())

    # controller.control_send_parameters()
    # controller.control_rec_setup(
    #     emulated=True,
    # )
    # controller.control_rec_start()
    # print(controller)
    # controller.control_rec_stop()
    # print(controller)
    # controller.stim_sweep()
