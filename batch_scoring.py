"""
Run trained PredNet on UCSD sequences to create data for anomaly detection
"""

import hickle as hkl
import os
import numpy as np
import matplotlib

import pandas as pd

from keras.models import Model as Model_keras
from keras.models import model_from_json
from keras.layers import Input
import tensorflow as tf

from models.prednet.prednet import PredNet
from models.prednet.data_utils import TestsetGenerator
import argparse

matplotlib.use("Agg")

# Define args
parser = argparse.ArgumentParser(description="Process input arguments")
parser.add_argument(
    "--scored_data",
    default="./data/scored_data/",
    type=str,
    dest="scored_data",
    help=("path to data and annotations (annotations should be in"
          "<data_dir>/<dataset>/Test/<dataset>.m"),
)
parser.add_argument(
    "--preprocessed_data",
    default="./data/preprocessed/",
    type=str,
    dest="preprocessed_data",
    help=("path to data and annotations (annotations should"
          "be in <data_dir>/<dataset>/Test/<dataset>.m"),
)
parser.add_argument(
    "--prednet_path",
    default="prednet_path",
    type=str,
    dest="prednet_path",
    help=("path to prednet model"),
)
parser.add_argument(
    "--dataset",
    default="UCSDped1",
    type=str,
    dest="dataset",
    help="dataset we are using",
)
parser.add_argument(
    "--nt", default=200, type=int, dest="nt", help="length of video sequences"
)
parser.add_argument(
    "--n_plot",
    default=0,
    type=int,
    dest="n_plot",
    help="How many sample sequences to plot",
)
parser.add_argument(
    "--batch_size",
    default=10,
    type=int,
    dest="batch_size",
    help="How many epochs per batch",
)
parser.add_argument(
    "--N_seq",
    default=None,
    type=int,
    dest="N_seq",
    help="how many videos per epoch",
)
parser.add_argument(
    "--save_prediction_error_video_frames",
    action="store_true",
    dest="save_prediction_error_video_frames",
    help="how many videos per epoch",
)

args = parser.parse_args()

if tf.test.is_gpu_available():
    print("We have a GPU")
else:
    print("Did not find GPU")

# check/create path for saving output
# extent data_dir for current dataset
scored_data = os.path.join(args.scored_data, args.dataset, "Test")
os.makedirs(scored_data, exist_ok=True)

# load the dataset
test_file = os.path.join(
    args.preprocessed_data,
    args.dataset,
    "X_test.hkl")
test_sources = os.path.join(
    args.preprocessed_data,
    args.dataset,
    "sources_test.hkl")
X = hkl.load(test_file)
sources = hkl.load(test_sources)

weights_file = os.path.join(args.prednet_path, "outputs", "weights.hdf5")
json_file = os.path.join(args.prednet_path, "outputs", "model.json")
print("weight and json file")
print(weights_file)
print(json_file)
with open(json_file, "r") as f:
    json_string = f.read()
trained_model = model_from_json(
    json_string, custom_objects={"PredNet": PredNet}
)
trained_model.load_weights(weights_file, by_name=True, skip_mismatch=True)

# Create testing model (to output predictions)
layer_config = trained_model.layers[1].get_config()
layer_config["output_mode"] = "prediction"
data_format = (
    layer_config["data_format"]
    if "data_format" in layer_config
    else layer_config["dim_ordering"]
)
prednet = PredNet(
    weights=trained_model.layers[1].get_weights(), **layer_config
)
input_shape = list(trained_model.layers[0].batch_input_shape[1:])
input_shape[0] = args.nt
inputs = Input(shape=tuple(input_shape))
predictions = prednet(inputs)
test_model = Model_keras(inputs=inputs, outputs=predictions)

# Define Generator for test sequences
test_generator = TestsetGenerator(
    test_file,
    test_sources,
    args.nt,
    data_format=data_format,
    N_seq=args.N_seq
)
X_test = test_generator.create_all()

# Apply model to the test sequences
X_hat = test_model.predict(X_test, args.batch_size)
if data_format == "channels_first":
    X_test = np.transpose(X_test, (0, 1, 3, 4, 2))
    X_hat = np.transpose(X_hat, (0, 1, 3, 4, 2))

# Compare MSE of PredNet predictions vs. using last frame, without
# aggregating across frames
model_err = X_test - X_hat
model_err[:, 0, :, :, :] = 0  # first frame doesn't count

# look at all timesteps except the first
model_mse = np.mean((model_err) ** 2, axis=(2, 3, 4))
model_p_50 = np.percentile((model_err) ** 2, 50, axis=(2, 3, 4))
model_p_75 = np.percentile((model_err) ** 2, 75, axis=(2, 3, 4))
model_p_90 = np.percentile((model_err) ** 2, 90, axis=(2, 3, 4))
model_p_95 = np.percentile((model_err) ** 2, 95, axis=(2, 3, 4))
model_p_99 = np.percentile((model_err) ** 2, 99, axis=(2, 3, 4))
model_std = np.std((model_err) ** 2, axis=(2, 3, 4))

# now we flatten them so that they are all in one column later
model_mse = np.reshape(model_mse, np.prod(model_mse.shape))
model_p_50 = np.reshape(model_p_50, np.prod(model_mse.shape))
model_p_75 = np.reshape(model_p_75, np.prod(model_mse.shape))
model_p_90 = np.reshape(model_p_90, np.prod(model_mse.shape))
model_p_95 = np.reshape(model_p_95, np.prod(model_mse.shape))
model_p_99 = np.reshape(model_p_99, np.prod(model_mse.shape))
model_std = np.reshape(model_std, np.prod(model_mse.shape))

# save the results to a dataframe
df = pd.DataFrame(
    {
        "model_mse": model_mse,
        "model_p_50": model_p_50,
        "model_p_75": model_p_75,
        "model_p_90": model_p_90,
        "model_p_95": model_p_95,
        "model_p_99": model_p_99,
        "model_std": model_std,
    }
)
df.to_pickle(os.path.join(args.scored_data, "df.pkl.gz"))
