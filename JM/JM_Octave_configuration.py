"""
Octave configuration working for QOP222 and qm-qua==1.1.5 and newer.
"""
from JM_set_octave import OctaveUnit, octave_declaration

######################
# Network parameters #
######################
qop_ip = "192.168.88.254"  # Write the QM router IP address
cluster_name = "Cluster_1"  # Write your cluster_name if version >= QOP220
qop_port = None  # Write the QOP port if version < QOP220

############################
# Set octave configuration #
############################
octave_port = 11235  # Must be 11xxx, where xxx are the last three digits of the Octave IP address
octave_1 = OctaveUnit("octave1", "192.168.88.234", port=80, con="con1")

# Add the octaves
octaves = [octave_1]
# Configure the Octaves
octave_config = octave_declaration(octaves)

#####################
# OPX configuration #
#####################
IF = 1e8
LO = 2e9
con = "con1"
octave = "octave1"
config = {
    "version": 1,
    "controllers": {
        con: {
            "analog_outputs": {
                1: {"offset": 0.0},
                2: {"offset": 0.0},
                3: {"offset": 0.0},
                4: {"offset": 0.0},
                5: {"offset": 0.0},
                6: {"offset": 0.0},
                7: {"offset": 0.0},
                8: {"offset": 0.0},
                9: {"offset": 0.0},
                10: {"offset": 0.0},
            },
            "digital_outputs": {
                1: {},
                3: {},
                5: {},
                7: {},
                9: {},
            },
            "analog_inputs": {
                1: {"offset": 0.0},
                2: {"offset": 0.0},
            },
        }
    },
    "elements": {
        "qe1": {
            "RF_inputs": {"port": (octave, 1)},
            "RF_outputs": {"port": (octave, 1)},
            "intermediate_frequency": IF,
            "operations": {
                "cw": "const",
                "readout": "pi_by_2",
                "jm": "jm_pulse",
            },
            "digitalInputs": {
                "switch": {
                    "port": (con, 1),
                    "delay": 0,
                    "buffer": 0,
                },
            },
            "time_of_flight": 24,
            "smearing": 0,
        },
        "qe2": {
            "RF_inputs": {"port": (octave, 2)},
            "RF_outputs": {"port": (octave, 2)},
            "intermediate_frequency": IF,
            "operations": {
                "cw": "const",
                "readout": "pi_by_2",
            },
            "digitalInputs": {
                "switch": {
                    "port": (con, 3),
                    "delay": 87,
                    "buffer": 15,
                },
            },
            "time_of_flight": 24,
            "smearing": 0,
        },
        "qe3": {
            "RF_inputs": {"port": (octave, 3)},
            "intermediate_frequency": IF,
            "operations": {
                "cw": "const",
                "readout": "pi_by_2",
            },
            "digitalInputs": {
                "switch": {
                    "port": (con, 5),
                    "delay": 136,
                    "buffer": 0,
                },
            },
        },
        "qe4": {
            "RF_inputs": {"port": (octave, 4)},
            "intermediate_frequency": IF,
            "operations": {
                "cw": "const",
                "readout": "pi_by_2",
            },
            "digitalInputs": {
                "switch": {
                    "port": (con, 7),
                    "delay": 87,
                    "buffer": 15,
                },
            },
        },
        "qe5": {
            "RF_inputs": {"port": (octave, 5)},
            "intermediate_frequency": IF,
            "operations": {
                "cw": "const",
                "readout": "pi_by_2",
            },
            "digitalInputs": {
                "switch": {
                    "port": (con, 9),
                    "delay": 87,
                    "buffer": 15,
                },
            },
        },
    },
    "octaves": {
        octave: {
            "RF_outputs": {
                1: {
                    "LO_frequency": LO,
                    "LO_source": "internal",  # can be external or internal. internal is the default
                    "output_mode": "triggered",  # can be: "always_on" / "always_off"/ "triggered" / "triggered_reversed". "always_off" is the default
                    "gain": 0,  # can be in the range [-20 : 0.5 : 20]dB
                },
                2: {
                    "LO_frequency": LO,
                    "LO_source": "internal",
                    "output_mode": "always_on",
                    "gain": 0,
                },
                3: {
                    "LO_frequency": LO,
                    "LO_source": "internal",
                    "output_mode": "always_on",
                    "gain": 0,
                },
                4: {
                    "LO_frequency": LO,
                    "LO_source": "internal",
                    "output_mode": "always_on",
                    "gain": 0,
                },
                5: {
                    "LO_frequency": LO,
                    "LO_source": "internal",
                    "output_mode": "always_on",
                    "gain": 0,
                },
            },
            "RF_inputs": {
                1: {
                    "LO_frequency": LO,
                    "LO_source": "internal",  # internal is the default
                    "IF_mode_I": "direct",  # can be: "direct" / "mixer" / "envelope" / "off". direct is default
                    "IF_mode_Q": "direct",
                },
                2: {
                    "LO_frequency": LO,
                    "LO_source": "external",  # external is the default
                    "IF_mode_I": "direct",
                    "IF_mode_Q": "direct",
                },
            },
            "connectivity": con,
        }
    },
    "pulses": {
        "const": {
            "operation": "control",
            "length": 16,
            "waveforms": {
                "I": "const_wf",
                "Q": "zero_wf",
            },
            "digital_marker": "ON",
        },
        "pi_by_2": {
            "operation": "measurement",
            "length": 60,
            "waveforms": {
                "I": "readout_wf",
                "Q": "zero_wf",
            },
            "integration_weights": {
                "cos": "cosine_weights",
                "sin": "sine_weights",
                "minus_sin": "minus_sine_weights",
            },
            "digital_marker": "ON",
        },
        "jm_pulse": {
            "operation": "control",
            "length": 16,
            "waveforms": {
                "I": "const_wf",
                "Q": "zero_wf",
            },
            "digital_marker": "ON",
        },
    },
    "waveforms": {
        "zero_wf": {
            "type": "constant",
            "sample": 0.0,
        },
        "const_wf": {
            "type": "constant",
            "sample": 0.125,
        },
        "readout_wf": {
            "type": "constant",
            "sample": 0.125,
        },

    },
    "digital_waveforms": {
        "ON": {"samples": [(1, 0)]},
        "OFF": {"samples": [(0, 0)]},
    },
    "integration_weights": {
        "cosine_weights": {
            "cosine": [(1.0, 1000)],
            "sine": [(0.0, 1000)],
        },
        "sine_weights": {
            "cosine": [(0.0, 1000)],
            "sine": [(1.0, 1000)],
        },
        "minus_sine_weights": {
            "cosine": [(0.0, 1000)],
            "sine": [(-1.0, 1000)],
        },
    },
}
