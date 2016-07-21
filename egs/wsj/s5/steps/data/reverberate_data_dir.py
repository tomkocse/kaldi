#!/usr/bin/env python
# Copyright 2016  Tom Ko
# Apache 2.0
# script to generate reverberated data

# we're using python 3.x style print but want it to work in python 2.x,
from __future__ import print_function
import argparse, glob, math, os, random, sys, warnings, copy, imp, ast

data_lib = imp.load_source('dml', 'steps/data/data_dir_manipulation_lib.py')

def GetArgs():
    # we add required arguments as named arguments for readability
    parser = argparse.ArgumentParser(description="Reverberate the data directory with an option "
                                                 "to add isotropic and point source noises. "
                                                 "Usage: reverberate_data_dir.py [options...] <in-data-dir> <out-data-dir> "
                                                 "E.g. reverberate_data_dir.py --rir-list-file rir_list "
                                                 "--foreground-snrs 20:10:15:5:0 --background-snrs 20:10:15:5:0 "
                                                 "--noise-list-file noise_list --speech-rvb-probability 1 --num-replications 2 "
                                                 "--random-seed 1 data/train data/train_rvb",
                                     formatter_class=argparse.ArgumentDefaultsHelpFormatter)

    parser.add_argument("--rir-list-file", type=str, required = True, 
                        help="RIR information file, the format of the file is "
                        "--rir-id <string,required> --room-id <string,required> "
                        "--receiver-position-id <string,optional> --source-position-id <string,optional> "
                        "--rt-60 <float,optional> --drr <float, optional> <location(support Kaldi IO strings)> "
                        "E.g. --rir-id 00001 --room-id 001 --receiver-position-id 001 --source-position-id 00001 "
                        "--rt60 0.58 --drr -4.885 data/impulses/Room001-00001.wav")
    parser.add_argument("--noise-list-file", type=str, default = None,
                        help="Noise information file, the format of the file is"
                        "--noise-id <string,required> --noise-type <choices = {isotropic, point source},required> "
                        "--bg-fg-type <choices = {background, foreground}, default=background> "
                        "--rir-file <str, specifies the rir file associated with the noise file. Required if isotropic "
                        "as the rir file links this noise file to a specific position in the room> "
                        "<location=(support Kaldi IO strings)> "
                        "E.g. --noise-id 001 --noise-type isotropic --rir-id 00019 iso_noise.wav")
    parser.add_argument("--num-replications", type=int, dest = "num_replicas", default = 1,
                        help="Number of replicate to generated for the data")
    parser.add_argument('--foreground-snrs', type=str, dest = "foreground_snr_string", default = '20:10:0', help='When foreground noises are being added the script will iterate through these SNRs.')
    parser.add_argument('--background-snrs', type=str, dest = "background_snr_string", default = '20:10:0', help='When background noises are being added the script will iterate through these SNRs.')
    parser.add_argument('--prefix', type=str, default = None, help='This prefix will modified for each reverberated copy, by adding additional affixes.')
    parser.add_argument("--speech-rvb-probability", type=float, default = 1.0,
                        help="Probability of reverberating a speech signal, e.g. 0 <= p <= 1")
    parser.add_argument("--pointsource-noise-addition-probability", type=float, default = 1.0,
                        help="Probability of adding point-source noises, e.g. 0 <= p <= 1")
    parser.add_argument("--isotropic-noise-addition-probability", type=float, default = 1.0,
                        help="Probability of adding isotropic noises, e.g. 0 <= p <= 1")
    parser.add_argument("--max-noises-per-minute", type=int, default = 2,
                        help="This controls the maximum number of point-source noises that could be added to a recording according to its duration")
    parser.add_argument('--random-seed', type=int, default=0, help='seed to be used in the randomization of impulses and noises')
    parser.add_argument("input_dir",
                        help="Input data directory")
    parser.add_argument("output_dir",
                        help="Output data directory")

    print(' '.join(sys.argv))

    args = parser.parse_args()
    args = CheckArgs(args)

    return args

def CheckArgs(args):
    if not os.path.exists(args.output_dir):
        os.makedirs(args.output_dir)

    ## Check arguments.
    if not os.path.isfile(args.rir_list_file):
        raise Exception(args.rir_list_file + "not found")
    
    if args.noise_list_file is not None:
        if not os.path.isfile(args.noise_list_file):
            raise Exception(args.noise_list_file + "not found")

    if args.num_replicas > 1 and args.prefix is None:
        args.prefix = "rvb"
        warnings.warn("--prefix is set to 'rvb' as --num-replications is larger than 1.")

    return args


class list_cyclic_iterator:
  def __init__(self, list):
    self.list_index = 0
    self.list = list
    random.shuffle(self.list)

  def next(self):
    item = self.list[self.list_index]
    self.list_index = (self.list_index + 1) % len(self.list)
    return item


# This functions picks an item from the collection according to the associated probability distribution.
# The probability estimate of each item in the collection is stored in the "probability" field of 
# the particular item. x : a collection (list or dictionary) where the values contain a field called probability
def PickItemWithProbability(x):
   if isinstance(x, dict):
     plist = list(set(x.values()))
   else:
     plist = x
   total_p = sum(item.probability for item in plist)
   p = random.uniform(0, total_p)
   accumulate_p = 0
   for item in plist:
      if accumulate_p + item.probability >= p:
         return item
      accumulate_p += item.probability
   assert False, "Shouldn't get here as the accumulated probability should always equal to 1"


# This function parses a file and pack the data into a dictionary
# It is useful for parsing file like wav.scp, utt2spk, text...etc
def ParseFileToDict(file, assert2fields = False, value_processor = None):
    if value_processor is None:
        value_processor = lambda x: x[0]

    dict = {}
    for line in open(file, 'r'):
        parts = line.split()
        if assert2fields:
            assert(len(parts) == 2)

        dict[parts[0]] = value_processor(parts[1:])
    return dict

# This function creates a file and write the content of a dictionary into it
def WriteDictToFile(dict, file_name):
    file = open(file_name, 'w')
    keys = dict.keys()
    keys.sort()
    for key in keys:
        value = dict[key]
        if type(value) in [list, tuple] :
            if type(value) is tuple:
                value = list(value)
            value.sort()
            value = ' '.join(str(value))
        file.write('{0}\t{1}\n'.format(key, value))
    file.close()


# This function returns only the isotropic noises according to the specified RIR id
# Please refer to ParseNoiseList() for the format of iso_noise_list
def FilterIsotropicNoiseList(iso_noise_list, rir_id):
    filtered_list = []
    for noise in iso_noise_list:
        if noise.rir_id == rir_id:
            filtered_list.append(noise)

    return filtered_list


def AddPointSourceNoise(noise_addition_descriptor,  # descriptor to store the information of the noise added
                        room,  # the room selected
                        pointsource_noise_list, # the point source noise list
                        pointsource_noise_addition_probability, # Probability of adding point-source noises
                        foreground_snrs, # the SNR for adding the foreground noises
                        background_snrs, # the SNR for adding the background noises
                        speech_dur,  # duration of the recording
                        max_noises_recording  # Maximum number of point-source noises that can be added
                        ):
    if len(pointsource_noise_list) > 0 and random.random() < pointsource_noise_addition_probability:
        for k in range(random.randint(1, max_noises_recording)):
            # pick the RIR to reverberate the point-source noise
            noise = PickItemWithProbability(pointsource_noise_list)
            noise_rir = PickItemWithProbability(room.rir_list)
            # If it is a background noise, the noise will be extended and be added to the whole speech
            # if it is a foreground noise, the noise will not extended and be added at a random time of the speech
            if noise.bg_fg_type == "background":
                noise_addition_descriptor['noise_io'].append("wav-reverberate --duration={2} --impulse-response={1} {0} - |".format(noise.noise_file_location, noise_rir.rir_file_location, speech_dur))
                noise_addition_descriptor['start_times'].append(0)
                noise_addition_descriptor['snrs'].append(background_snrs.next())
            else:
                noise_addition_descriptor['noise_io'].append("wav-reverberate --impulse-response={1} {0} - |".format(noise.noise_file_location, noise_rir.rir_file_location))
                noise_addition_descriptor['start_times'].append(round(random.random() * speech_dur, 2))
                noise_addition_descriptor['snrs'].append(foreground_snrs.next())

    return noise_addition_descriptor


def GenerateReverberationOpts(room_dict,  # the room dictionary, please refer to MakeRoomDict() for the format
                            pointsource_noise_list, # the point source noise list
                            iso_noise_list, # the isotropic noise list
                            foreground_snrs, # the SNR for adding the foreground noises
                            background_snrs, # the SNR for adding the background noises
                            speech_rvb_probability, # Probability of reverberating a speech signal
                            isotropic_noise_addition_probability, # Probability of adding isotropic noises
                            pointsource_noise_addition_probability, # Probability of adding point-source noises
                            speech_dur,  # duration of the recording
                            max_noises_recording  # Maximum number of point-source noises that can be added
                            ):
    reverberate_opts = ""
    noise_addition_descriptor = {'noise_io': [],
                                 'start_times': [],
                                 'snrs': []}
    # Randomly select the room
    # Here the room probability is a sum of the probabilities of the RIRs recorded in the room.
    room = PickItemWithProbability(room_dict)
    # Randomly select the RIR in the room
    speech_rir = PickItemWithProbability(room.rir_list)
    if random.random() < speech_rvb_probability:
        # pick the RIR to reverberate the speech
        reverberate_opts += "--impulse-response={0} ".format(speech_rir.rir_file_location)

    rir_iso_noise_list = FilterIsotropicNoiseList(iso_noise_list, speech_rir.rir_id)
    # Add the corresponding isotropic noise associated with the selected RIR
    if len(rir_iso_noise_list) > 0 and random.random() < isotropic_noise_addition_probability:
        isotropic_noise = PickItemWithProbability(rir_iso_noise_list)
        # extend the isotropic noise to the length of the speech waveform
        noise_addition_descriptor['noise_io'].append("wav-reverberate --duration={1} {0} - |".format(isotropic_noise.noise_file_location, speech_dur))
        noise_addition_descriptor['start_times'].append(0)
        noise_addition_descriptor['snrs'].append(background_snrs.next())

    noise_addition_descriptor = AddPointSourceNoise(noise_addition_descriptor,  # descriptor to store the information of the noise added
                                                    room,  # the room selected
                                                    pointsource_noise_list, # the point source noise list
                                                    pointsource_noise_addition_probability, # Probability of adding point-source noises
                                                    foreground_snrs, # the SNR for adding the foreground noises
                                                    background_snrs, # the SNR for adding the background noises
                                                    speech_dur,  # duration of the recording
                                                    max_noises_recording  # Maximum number of point-source noises that can be added
                                                    )

    assert len(noise_addition_descriptor['noise_io']) == len(noise_addition_descriptor['start_times'])
    assert len(noise_addition_descriptor['noise_io']) == len(noise_addition_descriptor['snrs'])
    if len(noise_addition_descriptor['noise_io']) > 0:
        reverberate_opts += "--additive-signals='{0}' ".format(','.join(noise_addition_descriptor['noise_io']))
        reverberate_opts += "--start-times='{0}' ".format(','.join(map(lambda x:str(x), noise_addition_descriptor['start_times'])))
        reverberate_opts += "--snrs='{0}' ".format(','.join(map(lambda x:str(x), noise_addition_descriptor['snrs'])))

    return reverberate_opts

# This function generates a new id from the input id
# This is needed when we have to create multiple copies of the original data
def GetNewId(id, prefix=None, copy=0):
    if prefix is not None:
        new_id = prefix + str(copy) + "_" + id
    else:
        new_id = id

    return new_id
    

# This is the main function to generate pipeline command for the corruption
# The generic command of wav-reverberate will be like:
# wav-reverberate --duration=t --impulse-response=rir.wav 
# --additive-signals='noise1.wav,noise2.wav' --snrs='snr1,snr2' --start-times='s1,s2' input.wav output.wav
def GenerateReverberatedWavScp(wav_scp,  # a dictionary whose values are the Kaldi-IO strings of the speech recordings
               durations, # a dictionary whose values are the duration (in sec) of the speech recordings
               output_dir, # output directory to write the corrupted wav.scp 
               room_dict,  # the room dictionary, please refer to MakeRoomDict() for the format
               pointsource_noise_list, # the point source noise list
               iso_noise_list, # the isotropic noise list
               foreground_snr_array, # the SNR for adding the foreground noises
               background_snr_array, # the SNR for adding the background noises
               num_replicas, # Number of replicate to generated for the data
               prefix, # prefix for the id of the corrupted utterances
               speech_rvb_probability, # Probability of reverberating a speech signal
               isotropic_noise_addition_probability, # Probability of adding isotropic noises
               pointsource_noise_addition_probability, # Probability of adding point-source noises
               max_noises_per_minute # maximum number of point-source noises that can be added to a recording according to its duration
               ):
    foreground_snrs = list_cyclic_iterator(foreground_snr_array)
    background_snrs = list_cyclic_iterator(background_snr_array)
    corrupted_wav_scp = {}
    for i in range(num_replicas):
        keys = wav_scp.keys()
        keys.sort()
        for recording_id in keys:
            wav_original_pipe = wav_scp[recording_id]
            # check if it is really a pipe
            if len(wav_original_pipe.split()) == 1:
                wav_original_pipe = "cat {0} |".format(wav_original_pipe)
            speech_dur = durations[recording_id]
            max_noises_recording = math.floor(max_noises_per_minute * speech_dur / 60)

            reverberate_opts = GenerateReverberationOpts(room_dict,  # the room dictionary, please refer to MakeRoomDict() for the format
                                                         pointsource_noise_list, # the point source noise list
                                                         iso_noise_list, # the isotropic noise list
                                                         foreground_snrs, # the SNR for adding the foreground noises
                                                         background_snrs, # the SNR for adding the background noises
                                                         speech_rvb_probability, # Probability of reverberating a speech signal
                                                         isotropic_noise_addition_probability, # Probability of adding isotropic noises
                                                         pointsource_noise_addition_probability, # Probability of adding point-source noises
                                                         speech_dur,  # duration of the recording
                                                         max_noises_recording  # Maximum number of point-source noises that can be added
                                                         )       
            
            if reverberate_opts == "":
                wav_corrupted_pipe = "{0}".format(wav_original_pipe) 
            else:
                wav_corrupted_pipe = "{0} wav-reverberate {1} - - |".format(wav_original_pipe, reverberate_opts)

            new_recording_id = GetNewId(recording_id, prefix, i)
            corrupted_wav_scp[new_recording_id] = wav_corrupted_pipe

    WriteDictToFile(corrupted_wav_scp, output_dir + "/wav.scp")


# This function replicate the entries in files like segments, utt2spk, text
def AddPrefixToFields(input_file, output_file, num_replicas, prefix, field = [0]):
    list = map(lambda x: x.strip(), open(input_file))
    f = open(output_file, "w")
    for i in range(num_replicas):
        for line in list:
            if len(line) > 0 and line[0] != ';':
                split1 = line.split()
                for j in field:
                    split1[j] = GetNewId(split1[j], prefix, i)
                print(" ".join(split1), file=f)
            else:
                print(line, file=f)
    f.close()


# This function creates multiple copies of the necessary files, e.g. utt2spk, wav.scp ...
def CreateReverberatedCopy(input_dir,
                           output_dir,
                           room_dict,  # the room dictionary, please refer to MakeRoomDict() for the format
                           pointsource_noise_list, # the point source noise list
                           iso_noise_list, # the isotropic noise list
                           foreground_snr_string, # the SNR for adding the foreground noises
                           background_snr_string, # the SNR for adding the background noises
                           num_replicas, # Number of replicate to generated for the data
                           prefix, # prefix for the id of the corrupted utterances
                           speech_rvb_probability, # Probability of reverberating a speech signal
                           isotropic_noise_addition_probability, # Probability of adding isotropic noises
                           pointsource_noise_addition_probability, # Probability of adding point-source noises
                           max_noises_per_minute  # maximum number of point-source noises that can be added to a recording according to its duration
                           ):
    
    if not os.path.isfile(input_dir + "/reco2dur"):
        print("Getting the duration of the recordings...");
        data_lib.RunKaldiCommand("wav-to-duration --read-entire-file=true scp:{0}/wav.scp ark,t:{0}/reco2dur".format(input_dir))
    durations = ParseFileToDict(input_dir + "/reco2dur", value_processor = lambda x: float(x[0]))
    wav_scp = ParseFileToDict(input_dir + "/wav.scp", value_processor = lambda x: " ".join(x))
    foreground_snr_array = map(lambda x: float(x), foreground_snr_string.split(':'))
    background_snr_array = map(lambda x: float(x), background_snr_string.split(':'))

    GenerateReverberatedWavScp(wav_scp, durations, output_dir, room_dict, pointsource_noise_list, iso_noise_list, 
               foreground_snr_array, background_snr_array, num_replicas, prefix, 
               speech_rvb_probability, isotropic_noise_addition_probability, 
               pointsource_noise_addition_probability, max_noises_per_minute)

    AddPrefixToFields(input_dir + "/utt2spk", output_dir + "/utt2spk", num_replicas, prefix, field = [0,1])
    data_lib.RunKaldiCommand("utils/utt2spk_to_spk2utt.pl <{output_dir}/utt2spk >{output_dir}/spk2utt"
                    .format(output_dir = output_dir))

    if os.path.isfile(input_dir + "/text"):
        AddPrefixToFields(input_dir + "/text", output_dir + "/text", num_replicas, prefix, field =[0])
    if os.path.isfile(input_dir + "/segments"):
        AddPrefixToFields(input_dir + "/segments", output_dir + "/segments", num_replicas, prefix, field = [0,1])
    if os.path.isfile(input_dir + "/reco2file_and_channel"):
        AddPrefixToFields(input_dir + "/reco2file_and_channel", output_dir + "/reco2file_and_channel", num_replicas, prefix, field = [0,1])

    data_lib.RunKaldiCommand("utils/validate_data_dir.sh --no-feats {output_dir}"
                    .format(output_dir = output_dir))


# This function smooths the probability distribution in the list
def SmoothProbabilityDistribution(list, smoothing_weight=0.3):
    uniform_probability = 1 / float(len(list))
    for item in list:
        if item.probability is None:
            item.probability = uniform_probability
        else:
            # smooth the probability
            item.probability = (1 - smoothing_weight) * item.probability + smoothing_weight * uniform_probability

    # Normalize the probability
    sum_p = sum(item.probability for item in list)
    for item in list:
        item.probability = item.probability / sum_p

    return list

# This function creates the RIR list 
# Each noise item in the list contains the following attributes:
# rir_id, room_id, receiver_position_id, source_position_id, rt60, drr, probability
# Please refer to the help messages in the parser for the meaning of these attributes
def ParseRirList(rir_list_file):
    rir_parser = argparse.ArgumentParser()
    rir_parser.add_argument('--rir-id', type=str, required=True, help='This id is unique for each RIR and the noise may associate with a particular RIR by refering to this id')
    rir_parser.add_argument('--room-id', type=str, required=True, help='This is the room that where the RIR is generated')
    rir_parser.add_argument('--receiver-position-id', type=str, default=None, help='receiver position id')
    rir_parser.add_argument('--source-position-id', type=str, default=None, help='source position id')
    rir_parser.add_argument('--rt60', type=float, default=None, help='RT60 is the time required for reflections of a direct sound to decay 60 dB.')
    rir_parser.add_argument('--drr', type=float, default=None, help='Direct-to-reverberant-ratio of the impulse.')
    rir_parser.add_argument('--probability', type=float, default=None, help='probability of the impulse.')
    rir_parser.add_argument('rir_file_location', type=str, help='rir file location')

    rir_list = []
    rir_lines = map(lambda x: x.strip(), open(rir_list_file))
    for line in rir_lines:
        rir = rir_parser.parse_args(line.split())
        setattr(rir, "iso_noise_list", [])
        rir_list.append(rir)

    return SmoothProbabilityDistribution(rir_list)


# This function divides the global RIR list into local lists
# according to the room where the RIRs are generated
# It returns the room dictionary indexed by the room id
# Its values are objects with two attributes: a local RIR list
# and the probability of the corresponding room
def MakeRoomDict(rir_list):
    room_dict = {}
    for rir in rir_list:
        if rir.room_id not in room_dict:
            # add new room
            room_dict[rir.room_id] = lambda: None
            setattr(room_dict[rir.room_id], "rir_list", [])
            setattr(room_dict[rir.room_id], "probability", 0)
        room_dict[rir.room_id].rir_list.append(rir)

    # the probability of the room is the sum of probabilities of its RIR
    for key in room_dict.keys():
        room_dict[key].probability = sum(rir.probability for rir in room_dict[key].rir_list)

    return room_dict

# This function creates the point-source noise list 
# and the isotropic noise list from the noise information file
# Each noise item in the list contains the following attributes:
# noise_id, noise_type, bg_fg_type, rir_id, probability, noise_file_location
# Please refer to the help messages in the parser for the meaning of these attributes
def ParseNoiseList(noise_list_file):
    noise_parser = argparse.ArgumentParser()
    noise_parser.add_argument('--noise-id', type=str, required=True, help='noise id')
    noise_parser.add_argument('--noise-type', type=str, required=True, help='the type of noise; i.e. isotropic or point-source', choices = ["isotropic", "point-source"])
    noise_parser.add_argument('--bg-fg-type', type=str, default="background", help='background or foreground noise', choices = ["background", "foreground"])
    noise_parser.add_argument('--rir-id', type=str, default=None, help='required if isotropic, should not be specified if point-source')
    noise_parser.add_argument('--probability', type=float, default=None, help='probability of the noise.')
    noise_parser.add_argument('noise_file_location', type=str, help='noise file location')

    pointsource_noise_list = []
    iso_noise_list = []
    noise_lines = map(lambda x: x.strip(), open(noise_list_file))
    for line in noise_lines:
        noise = noise_parser.parse_args(line.split())
        if noise.noise_type == "isotropic":
            if noise.rir_id is None:
                raise Exception("--rir-id must be specified if --noise-type is isotropic")
            else:
                iso_noise_list.append(noise)
        else:
            pointsource_noise_list.append(noise)

    return (SmoothProbabilityDistribution(pointsource_noise_list),
            SmoothProbabilityDistribution(iso_noise_list))


def Main():
    args = GetArgs()
    random.seed(args.random_seed)
    rir_list = ParseRirList(args.rir_list_file)
    noise_list = []
    if args.noise_list_file is not None:
        pointsource_noise_list, iso_noise_list = ParseNoiseList(args.noise_list_file)
        print("Number of point-source noises is {0}".format(len(pointsource_noise_list)))
        print("Number of isotropic noises is {0}".format(len(iso_noise_list)))
    room_dict = MakeRoomDict(rir_list)

    CreateReverberatedCopy(input_dir = args.input_dir,
                   output_dir = args.output_dir,
                   room_dict = room_dict,
                   pointsource_noise_list = pointsource_noise_list,
                   iso_noise_list = iso_noise_list,
                   foreground_snr_string = args.foreground_snr_string,
                   background_snr_string = args.background_snr_string,
                   num_replicas = args.num_replicas,
                   prefix = args.prefix,
                   speech_rvb_probability = args.speech_rvb_probability,
                   isotropic_noise_addition_probability = args.isotropic_noise_addition_probability,
                   pointsource_noise_addition_probability = args.pointsource_noise_addition_probability,
                   max_noises_per_minute = args.max_noises_per_minute)

if __name__ == "__main__":
    Main()

