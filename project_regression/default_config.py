"""Default configuration.

Information to help elastic metric parameter choosing:
----------------------------------------
The elastic metric is a weighted sum of 3 terms:
    - TODO: add description of the terms

The weights are:
a0 = weighted l2 energy:
    penalizes how much you have to move points (vertices)
    weighted by local area around that vertex.
    Max value 1. If it's too high, it might shrink the mesh down,
    match and then blow up again

a1 = penalizes stretching (was 10)
b1 = penalizes shearing (was 10)
c1 = (was 1) penalizes change in normals:
    for high deformations we want c1 pretty low,
    e.g. when moving an arm.
    in our case try with a1 b1 a bit smaller (10),
    and c1 a bit large (1 or even up to 10)
d1 = (was 0) penalizes how a triangle rotate about normal vector,
    without stretching or shearing. almost never used
    it is everything that a1, b1, c1 don't penalize.

a2 = (was 1) high value = 1. a2 penalizes the laplacian of the mesh.
    it wants to get a smooth mesh.
    if it is too high, we will get bloating. It wants to blow the
    mesh up to get a super smooth mesh.
"""

import os
import subprocess
import sys

import torch

os.environ["GEOMSTATS_BACKEND"] = "pytorch"

# build work path from git root path
gitroot_path = subprocess.check_output(
    ["git", "rev-parse", "--show-toplevel"], universal_newlines=True
)
os.chdir(gitroot_path[:-1])
work_dir = os.getcwd()  # code/my28brains/
code_dir = os.path.dirname(work_dir)  # code/
raw_dir = "/home/data/28andMeOC_correct"
project_dir = os.path.join(
    os.getcwd(), "project_regression"
)  # code/my28brains/project_regression/
src_dir = os.path.join(os.getcwd(), "src")
h2_dir = os.path.join(os.getcwd(), "H2_SurfaceMatch")
sys.path.append(code_dir)
sys.path.append(h2_dir)

# WANDB API KEY
# Find it here: https://wandb.ai/authorize
# Story it in file: api_key.txt (without extra line break)
with open(os.path.join(src_dir, "api_key.txt")) as f:
    api_key = f.read()

# GPU Parameters
use_cuda = False  # use cuda if available
if use_cuda:
    device_id = 1
else:
    device_id = -1
n_gpus = 10
torch_dtype = torch.float64

# Saving geodesics using plotGeodesic
stepsize = {
    "synthetic_mesh": 55,
    "menstrual_mesh": 6,
}

# 1. Preprocessing Parameters

# Brain hemispheres and anatomical structures
hemisphere = ["left"]  # , "right"]
structure_ids = [-1]

# Face area threshold for non-degenerate meshes:
# the less we decimate, the more likely it is to have small faces
# thus the thresholt needs to be higher
area_thresholds = [0.00]  # 0.0001, 0.001, 0.01, 0.1, 1.0]

# WORKING
initial_decimation_fact = 10
scaling_factor = 2 * initial_decimation_fact
# NOT WORKING
# initial_decimation_fact = 4
# scaling_factor = 10

# Define template structure of the mesh that will be used
# for all mesh in the interpolation
# Every mesh will have the same number of vertices and faces.
i_template = 0
template_day_index = 2

# range of days to interpolate in between
# Looking at the first 10 days is interesting because:
# - we have 10 gpus, so we can run 10 interpolations at once
# - they contain most of the progesterone peak.
# first menstrual cycle is day 1-30 (pre-pill)

day_range = [2, 11]  # we have parameterized meshes for days 2-11


run_interpolate = False

# 2. Regression Parameters

# Noise Models:
# Model 1: Geodesic Noise
# Model 2: Unprojected Linear Noise
# Model 3: Projected Linear Noise
# Model 4: Submersed Linear Noise

model = 3  # 1, 2, 3, 4

if model == 1:
    linear_noise = False
    project_linear_noise = False
    dataset_name = [
        "hyperboloid",
        "hypersphere",
    ]
    space_dimension = [2]  # [2, 3, 5, 10] hyperboloid GLS, LLS, Lin2015.
if model == 2:  # TODO: PLS
    linear_noise = True
    project_linear_noise = False
    dataset_name = [
        "hyperboloid",
        "hypersphere",
    ]
    space_dimension = [2]
if model == 3:  # TODO: PLS
    linear_noise = True
    project_linear_noise = True
    # Note that we only use hyperboloid and hypersphere data for this model
    dataset_name = [
        "hyperboloid",
        "hypersphere",
    ]
    space_dimension = [2]
if model == 4:  # only do for dim 2
    linear_noise = True
    project_linear_noise = True
    # note we only use mesh data for this model,
    # and the "projection" is actually a submersion
    dataset_name = ["synthetic_mesh"]

# Estimators:
# GLS: Geodesic Least Squares applied to geodesic regression --> don't apply to model 2
# LLS: Linear Least Squares applied to geodesic regression
# Lin2015: Linear Least Squares applied to linear regression, then projected to the manifold.
if model == 2:
    estimator = ["PLS"]  # ["LLS", "Lin2015", "LR"]
else:
    estimator = ["PLS"]  # ["GLS", "LLS", "Lin2015", "LR"]

n_steps = [3]  # n steps for the exp solver of geomstats. 3, 5
synthetic_tan_vec_length = [
    1,
    5,
    10,
]  # done for 1 -- for hypersphere and hyperboloid only
random_seed = [0, 4, 7, 47, 474]  # 0, 1, 2, 3, 4, 5, 6, 7, 8, 9
tol_factor = [
    0.01,
    # 0.1,
]  # tolerance for geodesic regression. If none logged, value 0.001.
n_X = [
    5,
    10,
    20,
    30,
]  # Only for dataset_name == synthetic
start_shape = [
    "cube"
]  # "cube", "distorted_cube", 'twisted_cube', "sphere", "ellipsoid",
end_shape = ["twisted_cube"]  # note, must have same number of shapes as start_shape
noise_factor = [
    0.0,
    0.01,
    0.1,
    0.2,
    0.4,
    0.6,
]  # , 0.0001, 0.001, 0.01]  # noise added to the data.
# Will be multiplied by the size of the mesh to calculate the standard
# deviation of added noise distribution.
# only applied to synthetic data.
if start_shape == ["sphere"] or start_shape == ["ellipsoid"]:
    n_subdivisions = [1]  # , 1, 2, 3, 4, 5]
elif (
    start_shape == ["cube"]
    or start_shape == ["distorted_cube"]
    or start_shape == ["twisted_cube"]
):
    n_subdivisions = ["None"]

# How many X to subdivide the mesh. Note that the number of faces will grow
# as function of 4 ** subdivisions, so you probably want to keep this under ~5.
# if nothing recorded, value 3.
ellipsoid_dims = [[2, 2, 3]]
# [2, 2, 10],
# [10, 10, 2],
# [2, 2, 6],]  # if nothing recorded, [2, 2, 3]

# Build Paths

# Data (inside project_dir : my28brains/project_regression/)
data_dir = os.path.join(project_dir, "data")
synthetic_data_dir = os.path.join(data_dir, "synthetic_mesh")

# Results (inside project_dir : my28brains/project_regression/)
results_dir = os.path.join(project_dir, "results")
tmp_dir = os.path.join(results_dir, "tmp")

preprocess_dir = os.path.join(results_dir, "1_preprocess")
meshed_dir = os.path.join(preprocess_dir, "a_meshed")
centered_dir = os.path.join(preprocess_dir, "b_centered")
nondegenerate_dir = os.path.join(preprocess_dir, "c_nondegenerate")
reparameterized_dir = os.path.join(preprocess_dir, "d_reparameterized")
sorted_dir = os.path.join(preprocess_dir, "e_sorted")
interpolated_dir = os.path.join(preprocess_dir, "f_interpolated")

regression_dir = os.path.join(results_dir, "2_regression")

for mesh_dir in [
    synthetic_data_dir,
    preprocess_dir,
    meshed_dir,
    centered_dir,
    nondegenerate_dir,
    reparameterized_dir,
    sorted_dir,
    interpolated_dir,
    regression_dir,
]:
    if not os.path.exists(mesh_dir):
        os.makedirs(mesh_dir)


# Elastic Metric Parameters

a0 = 0.01  # was 0.1
a1 = 10  # (was 10)
b1 = 10  # (was 10)
c1 = 1  # (was 1)
d1 = 0
a2 = 1  # (was 1)

# Unparameterized Geodesic Parameters

# NOTE: "time_steps" is the number of time points that
#  we will have in the interpolated geodesic
# the "time_steps" value in the last param will set the number
# of time points in the interpolated geodesic
resolutions = 0  # don't do several resolutions for our case.

param1 = {
    "weight_coef_dist_T": 10**1,  # target varifold term
    "weight_coef_dist_S": 10**1,  # source varifold term
    "sig_geom": 0.4,
    "max_iter": 1000,  # bfgs gets really close really fast and someX
    # worth letting it run for a bunch of iterations + see scipy,
    # esp stopping condition to get decent figures
    "time_steps": 2,
    "tri_unsample": False,  # False
    "index": 0,  # spatial resolution, should increase everytime we to a trip_upsample.
}

param2 = {
    "weight_coef_dist_T": 10
    ** 5,  # increase exponentially bcs in SNRF orignal code they had it and it works
    "weight_coef_dist_S": 10**5,
    "sig_geom": 0.1,
    "max_iter": 1000,
    "time_steps": 3,
    "tri_unsample": False,
    "index": 0,
}
# important to have varifold term with high weight,
# to be sure that source + target are close to data.
# as the match gets better, the varifold terms are decreasing exponetially,
# thus we compensate back with the weights.
# could do 10**1 and 10**5 if we're only doing two parameters.
# e.g. with 3 parameters, emmanuel did: 10**1, 10**5, 10**10
# e.g. corresponding sig_geom: 0.4, 0.1, 0.025

param3 = {
    "weight_coef_dist_T": 10**10,
    "weight_coef_dist_S": 10**10,
    "sig_geom": 0.025,
    "max_iter": 2000,
    "time_steps": 5,
    "tri_unsample": False,
    "index": 0,
}

paramlist = [param1, param2, param3]  # , param4]  # param5, param6]
