import ast
import argparse
import logging
import matplotlib
from matplotlib import pyplot as plt
import os
import numpy as np
import torch
# Duckietown Specific
from ddpg import DDPG
from utils import seed, evaluate_policy, ReplayBuffer
from env import launch_env
from wrappers import NormalizeWrapper, ImgWrapper, DtRewardWrapper, ActionWrapper, ResizeWrapper
from args import get_ddpg_args_train
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)


def _train(args):
    policy_name = "DDPG1"

    print(f"Using {'cuda' if torch.cuda.is_available() else 'cpu'}")

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    #args = get_ddpg_args_train()

    if args.log_file != None:
        print('You asked for a log file. "Tee-ing" print to also print to file "' + args.log_file + '" now...')

    import subprocess, os, sys
    """
    tee = subprocess.Popen(["tee", args.log_file], stdin=subprocess.PIPE)
    # Cause tee's stdin to get a copy of our stdin/stdout (as well as that
    # of any child processes we spawn)
    os.dup2(tee.stdin.fileno(), sys.stdout.fileno())
    os.dup2(tee.stdin.fileno(), sys.stderr.fileno())
    """

    file_name = "{}_{}".format(
        policy_name,
        str(args.seed),
    )

    if not os.path.exists("./results"):
        os.makedirs("./results")
    if args.save_models and not os.path.exists("./pytorch_models"):
        os.makedirs("./pytorch_models")
    
    #if not os.path.exists("./results"):
     #   os.makedirs("./results")
    #if not os.path.exists(args.model_dir):
     #   os.makedirs(args.model_dir)

    # Launch the env with our helper function
    env = launch_env()
    print("Initialized environment")

    # Wrappers
    env = ResizeWrapper(env)
    env = NormalizeWrapper(env)
    env = ImgWrapper(env)  # to make the images from 160x120x3 into 3x160x120
    env = ActionWrapper(env)
    env = DtRewardWrapper(env)
    print("Initialized Wrappers")

    # Set seeds
    seed(args.seed)

    state_dim = env.observation_space.shape
    action_dim = env.action_space.shape[0]
    max_action = float(env.action_space.high[0])

    # Initialize policy
    policy = DDPG(state_dim, action_dim, max_action, net_type="dense")
    replay_buffer = ReplayBuffer(args.replay_buffer_max_size)
    print("Initialized DDPG")

    # Evaluate untrained policy
    evaluations = [evaluate_policy(env, policy)]

    total_timesteps = 0
    timesteps_since_eval = 0
    episode_num = 0
    done = True
    episode_reward = None
    env_counter = 0
    reward = 0
    episode_timesteps = 0
    print("Starting training")
    while total_timesteps < args.max_timesteps:

        print("timestep: {} | reward: {}".format(total_timesteps, reward))

        if done:
            if total_timesteps != 0:
                print(
                    ("Total T: %d Episode Num: %d Episode T: %d Reward: %f")
                    % (total_timesteps, episode_num, episode_timesteps, episode_reward)
                )
                policy.train(replay_buffer, episode_timesteps, args.batch_size, args.discount, args.tau)

                # Evaluate episode
                if timesteps_since_eval >= args.eval_freq:
                    timesteps_since_eval %= args.eval_freq
                    evaluations.append(evaluate_policy(env, policy))
                    print("rewards at time {}: {}".format(total_timesteps, evaluations[-1]))

                    if True:
                        policy.save(file_name, directory="./pytorch_models")
                    np.savez("./results/{}.npz".format(file_name), evaluations)
                 
            # Reset environment
            env_counter += 1
            obs = env.reset()
            done = False
            episode_reward = 0
            episode_num += 1

        # Select action randomly or according to policy
        if total_timesteps < args.start_timesteps:
            action = env.action_space.sample()
        else:
            action = policy.predict(np.array(obs))
            if args.expl_noise != 0:
                action = (action + abs(np.random.normal(0, args.expl_noise, size=env.action_space.shape[0]))).clip(
                    env.action_space.low, env.action_space.high
                )

        # Perform action
        new_obs, reward, done, _ = env.step(action)

        if episode_timesteps >= args.env_timesteps:
            done = True

        done_bool = 0 if episode_timesteps + 1 == args.env_timesteps else float(done)
        episode_reward += reward

        # Store data in replay buffer
        replay_buffer.add(obs, new_obs, action, reward, done_bool)

        obs = new_obs

        episode_timesteps += 1
        total_timesteps += 1
        timesteps_since_eval += 1
        if timesteps_since_eval >= args.eval_freq:
            timesteps_since_eval %= args.eval_freq
            evaluations.append(evaluate_policy(env, policy))
            print("rewards at time {}: {}".format(total_timesteps, evaluations[-1]))

            if True:
                policy.save(file_name, directory="./pytorch_models")
            np.savez("./results/{}.npz".format(file_name), evaluations)
    print("Training done, about to save..")
    policy.save(filename="ddpg", directory=args.model_dir)
    np.savez("./results/{}.npz".format(file_name), evaluations)
    print("Finished saving..should return now!")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()

    # DDPG Args
    parser.add_argument("--seed", default=0, type=int)  # Sets Gym, PyTorch and Numpy seeds
    parser.add_argument(
        "--start_timesteps", default=1e3, type=int
    )  # How many time steps purely random policy is run for
    parser.add_argument("--eval_freq", default=100, type=float)  # How often (time steps) we evaluate
    parser.add_argument("--max_timesteps", default=1e3, type=float)  # Max time steps to run environment for
    parser.add_argument("--save_models", action="store_true", default=True)  # Whether or not models are saved
    parser.add_argument("--expl_noise", default=0.1, type=float)  # Std of Gaussian exploration noise
    parser.add_argument("--batch_size", default=32, type=int)  # Batch size for both actor and critic
    parser.add_argument("--discount", default=0.99, type=float)  # Discount factor
    parser.add_argument("--tau", default=0.005, type=float)  # Target network update rate
    parser.add_argument(
        "--policy_noise", default=0.2, type=float
    )  # Noise added to target policy during critic update
    parser.add_argument("--noise_clip", default=0.5, type=float)  # Range to clip target policy noise
    parser.add_argument("--policy_freq", default=2, type=int)  # Frequency of delayed policy updates
    parser.add_argument("--env_timesteps", default=500, type=int)  # Frequency of delayed policy updates
    parser.add_argument(
        "--replay_buffer_max_size", default=1000, type=int
    )  # Maximum number of steps to keep in the replay buffer
    parser.add_argument("--model-dir", type=str, default="./pytorch_models")
    parser.add_argument(
        "--log_file", default=None, type=str
    )  # Maximum number of steps to keep in the replay buffer

    _train(parser.parse_args())
