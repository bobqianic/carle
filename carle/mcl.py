"""
endogenous reward system for open-ended learning. 
    mcl stands for mesocorticolimbic system, aka the reward system in the human brain
    
    These reward system classes act as wrappers around CARLE, and are invoked as

    `
    env = MotivatorClass(env)
    `

    Multiple wrappers can be applied in series, and the original CARLE environment can be 
    accessed as `env.inner_env`
"""
import os

import time
import numpy as np

import torch
import torch.nn as nn
import torch.nn.functional as F

import carle
from carle.env import CARLE

import matplotlib.pyplot as plt


class Motivator(nn.Module):

    def __init__(self, env, **kwargs):
        super(Motivator, self).__init__()
        
        if env.inner_env == None:
            self.inner_env = env
        else:
            self.inner_env = env.inner_env

        self.env = env

        self.height = self.inner_env.height
        self.width = self.inner_env.height
        self.action_height = self.inner_env.action_height
        self.action_width = self.inner_env.action_width
        self.birth = self.inner_env.birth
        self.survive = self.inner_env.survive
        self.my_device = self.inner_env.my_device

    def rules_from_string(self, my_string="B3/S23"):
    
        self.inner_env.rules_from_string(my_string)
        self.birth = self.inner_env.birth
        self.survive = self.inner_env.survive

    
    def birth_rule_from_string(self, my_string="b3"):

        self.inner_env.birth_rule_from_string(my_string)
        self.birth = self.inner_env.birth

    def survive_rule_from_string(self, my_string="s23"):

        self.inner_env.survive_rule_from_string(my_string)
        self.survive = self.inner_env.survive

    def reset(self):

        obs = self.env.reset()
        
        return obs

    def step(self, action):

        obs, reward, done, info = self.env.step(action)

        return obs, reward, done, info

    def set_no_grad(self):

        pass

    def set_grad(self):

        pass

class ParsimonyBonus(Motivator):
    """
    a bonus modulator that rewards being selective with actionsor doing less
    
    """

    def __init__(self, env, **kwargs):
        super(ParsimonyBonus, self).__init__(env, **kwargs) 

        # 128 cells represents about 3% of a 64 by 64 action space
        self.parsimony_threshold = 128

    def step(self, action):

        obs, reward, done, info = self.env.step(action)

        reward = 100.0 * reward / \
                (torch.max(action.sum(axis=[1,2,3]), torch.tensor([100.0])))

        return obs, reward, done, info
        
class MorphoBonus(Motivator):
    """
    A bonus for matching a desired body/machine plan
    """
    
    def __init__(self, env, **kwargs):
        super(MorphoBonus, self).__init__(env, **kwargs)

        self.use_grad = kwargs["use_grad"] if "kwargs"  in kwargs.keys() else False
        self.my_name = "MorphoBonus"

        self.reward_scale = 1.0
        self.target_patterns = torch.Tensor().to(self.my_device)

        self.add_default_patterns()

        if self.use_grad:
            # set all parameters in this wrapper and inner_env 
            # to requires_grad = True
            # note this currently doesn't support stalking multiple reward 
            # wrappers, will need to decide how to implement it

            for param in self.inner_env.parameters():
                param.requires_grad = True

            self.target_patterns.requires_grad = True

    def add_default_patterns(self):
    
        file_path = os.path.split(os.path.abspath(__file__))[0]
        
        #self.add_rle_pattern(os.path.join(file_path, "spaceship_duck.rle"))
        #self.add_rle_pattern(os.path.join(file_path, "spaceship_step.rle"))
        self.add_rle_pattern(os.path.join(file_path, "glider_1.rle"))
        self.add_rle_pattern(os.path.join(file_path, "glider_2.rle"))


    def add_rle_pattern(self, rle_path, dim=8):

        pad_1 = nn.ZeroPad2d((1,1,2,1))

        my_rle = self.inner_env.read_rle(rle_path)
        pattern = pad_1(self.inner_env.rle_to_grid(my_rle))[:dim, :dim]

        pattern[pattern == 0] = -1
        pattern = pattern.unsqueeze(0).unsqueeze(0).to(self.my_device)

        #normalize kernel
        pattern[pattern == 1] *= 15. / pattern[pattern==1].sum()

        self.target_patterns = torch.cat([self.target_patterns, pattern])
        self.target_patterns = torch.cat([self.target_patterns, \
                pattern.flip(2)])
        self.target_patterns = torch.cat([self.target_patterns, \
                pattern.flip(3)])
        self.target_patterns = torch.cat([self.target_patterns, \
                pattern.transpose(2,3).flip(2)])
        self.target_patterns = torch.cat([self.target_patterns, \
                pattern.transpose(2,3).flip(3)])
        self.target_patterns = torch.cat([self.target_patterns, \
                pattern.transpose(2,3)])
        

    def step(self, action):

        my_grid = torch.abs(self.inner_env.universe.clone() - action)
        conv_obs = F.conv2d(my_grid, self.target_patterns)

        obs, reward, done, info = self.env.step(action)

        my_max = torch.max(torch.max(torch.max(conv_obs, dim=3)[0], dim=2)[0], dim=1)[0]
        my_min = torch.min(torch.min(torch.min(conv_obs, dim=3)[0], dim=2)[0], dim=1)[0]


        reward += self.reward_scale * (my_max.unsqueeze(-1) + my_min.unsqueeze(-1)) #* conv_obs.max() + conv_obs.min()

        return obs, reward, done, info

    def reset(self):

        obs = self.env.reset()

        # imagine a little seed for nucleating patterns
        obs += (torch.rand(obs.shape) > 0.995).to(self.my_device).float()
        #obs = obs.to(self.my_device)
        #obs[:,:,32:35,32:35].fill(1.0)
        #obs += torch.rand_like(obs)
        
        return obs

class CornerBonus(Motivator):

    def __init__(self, env, **kwargs):
        super(CornerBonus, self).__init__(env, **kwargs)

        self.my_name = "CornerBonus"

        self.reward_scale = 1.0

        self.reward_mask = torch.zeros(1, 1, self.inner_env.height, \
                self.inner_env.width).to(self.my_device)
        self.punish_mask = torch.zeros(1, 1, self.inner_env.height, \
                self.inner_env.width).to(self.my_device)

        self.reward_mask[:, :, :16, :16] = 1.0
        for ii in range(96):
            self.reward_mask[:, :, ii-4:ii+4, ii-4:ii+4] = 1.0

        self.punish_mask[:, :, -64:, -64:] = -1.0
        self.punish_mask[:, :, :64, -64:] = -1.0

    def step(self, action):

        obs, reward, done, info = self.env.step(action)
        
        reward += self.reward_scale * (self.reward_mask * obs).sum(axis=-1).sum(axis=-1)
        reward += self.reward_scale * (self.punish_mask * obs).sum(axis=-1).sum(axis=-1)

        return obs, reward, done, info

    def reset(self):

        obs = self.env.reset()

        return obs

class RND2D(Motivator):
    """
    An implentation of random network distillation (Burda et al. 2018) 
    for 4d tensors representing 2D cellular automata universes
    """
    def __init__(self, env, **kwargs):
        super(RND2D, self).__init__(env, **kwargs)
        
        self.my_name = "RND2D"

        self.learning_rate = 6e-2

        self.reward_scale = 1.0
        self.rnd_dim = 16

        self.initialize_predictor()
        self.initialize_random_network()

        self.buffer_length = 0
        self.batch_size = 64

        self.updates = 0


    def initialize_predictor(self):

        print("initialize predictor")
        dense_nodes = (self.inner_env.width // 8) * (self.inner_env.height // 8)

        self.predictor = nn.Sequential(\
                nn.Conv2d(1, 4, 3, padding=1, stride=1),\
                nn.Dropout(p=0.1),\
                nn.ReLU(),\
                nn.MaxPool2d(2,2,padding=0),\
                nn.MaxPool2d(2,2,padding=0),\
                nn.Conv2d(4, 1, 3, padding=1, stride=1),\
                nn.Dropout(p=0.1),\
                nn.ReLU(),\
                nn.MaxPool2d(2,2,padding=0),\
                nn.Dropout(p=0.1),\
                nn.Flatten(),\
                nn.Linear(dense_nodes, self.rnd_dim),\
                nn.Tanh()\
                )

        self.optimizer = torch.optim.Adam(self.predictor.parameters(),\
                lr=self.learning_rate)

    def initialize_random_network(self):

        dense_nodes = (self.inner_env.width // 8) * (self.inner_env.height // 8)

        self.random_network = nn.Sequential(\
                nn.Conv2d(1, 2, 3, padding=1, stride=1),\
                nn.ReLU(),\
                nn.MaxPool2d(2,2,padding=0),\
                nn.MaxPool2d(2,2,padding=0),\
                nn.Conv2d(2, 1, 3, padding=1, stride=1),\
                nn.ReLU(),\
                nn.MaxPool2d(2,2,padding=0),\
                nn.Flatten(),\
                nn.Linear(dense_nodes, self.rnd_dim),\
                nn.Tanh()\
                )

        self.set_grad()

    def set_grad(self):


        for param in self.predictor.parameters():
            param.requires_grad = True

        for param in self.random_network.parameters():
            param.requires_grad = False
            

    def set_no_grad(self):


        for param in self.predictor.parameters():
            param.requires_grad = False

        for param in self.random_network.parameters():
            param.requires_grad = False

    def random_forward(self, obs):

        return self.random_network(obs)

    def forward(self, obs):
        """
        corresponds to forward pass of the predictor network
        """

        x = self.predictor(obs)

        return x


    def update_predictor(self, loss):

        loss.backward()

        self.optimizer.step()

        self.optimizer.zero_grad()

        self.updates += 1

    def get_bonus(self, obs):

        target = self.random_forward(obs)
        prediction = self.forward(obs)

        loss = torch.mean(torch.abs((target-prediction)**2),\
                dim=[1])

        # loss is a tensor used for vectorized rnd reward bonuses
        return loss

    def get_bonus_update(self, obs):

        self.predictor.zero_grad()

        # loss is a tensor used for vectorized rnd reward bonuses
        loss = self.get_bonus(obs)

        # update loss is a scalar used for backprop
        update_loss = torch.mean(loss)

        self.update_predictor(update_loss)

        return loss

    def get_bonus_accumulate(self, obs):

        if self.buffer_length == 0:
            self.predictor.zero_grad()
            self.accumulate_loss = 0.0

        loss = self.get_bonus(obs)

        self.accumulate_loss += torch.mean(loss)

        self.buffer_length += 1

        if self.buffer_length >= self.batch_size:
            self.accumulate_loss = self.accumulate_loss / self.batch_size

            self.update_predictor(self.accumulate_loss)
            self.buffer_length = 0

        return loss


    def get_bonus_only(self, obs):

        with torch.no_grad():

            loss = self.get_bonus(obs)

        return loss


    def step(self, action):

        action = action.to(self.inner_env.my_device)
        obs, reward, done, info = self.env.step(action)

        rnd_bonus = self.get_bonus_accumulate(obs).unsqueeze(1)

        reward += self.reward_scale * rnd_bonus

        return obs, reward, done, info

    def reset(self):

        #self.initialize_predictor()
        #self.initialize_random_network()
        

        obs = self.env.reset()

        self.to(self.inner_env.my_device)

        self.updates = 0

        return obs


class AE2D(RND2D):

    def __init__(self, env, **kwargs):
        super(AE2D, self).__init__(env, **kwargs)
        self.learning_rate = 9e-2

        self.my_name = "AE2D"


    def initialize_random_network(self):
        pass

    def forward(self, obs):

        prediction = self.predictor(obs)

        prediction = prediction.reshape(\
                self.inner_env.instances, 1, self.inner_env.height, self.inner_env.width)

        return prediction

    def initialize_predictor(self):
        print("initialize predictor")

        dense_in = (self.inner_env.width // 8) * (self.inner_env.height // 8)
        dense_out = (self.inner_env.width) * (self.inner_env.height)

        if(1):
            self.predictor = nn.Sequential(\
                    nn.Conv2d(1, 4, 3, padding=1, stride=1),\
                    nn.Dropout(p=0.1),\
                    nn.ReLU(),\
                    nn.MaxPool2d(2,2,padding=0),\
                    nn.Conv2d(4, 2, 3, padding=1, stride=1),\
                    nn.Dropout(p=0.1),\
                    nn.ReLU(),\
                    nn.MaxPool2d(2,2,padding=0),\
                    nn.ConvTranspose2d(2, 1, 4, padding=1, stride=2),\
                    nn.Dropout(p=0.1),\
                    nn.ReLU(),\
                    nn.ConvTranspose2d(1, 1, 4, padding=1, stride=2),\
                    nn.Dropout(p=0.1),\
                    nn.Sigmoid()\
                    )
        else:
            self.predictor = nn.Sequential(\
                    nn.Flatten(),\
                    nn.Linear(dense_out, 1024, bias=False),\
                    nn.ReLU(),\
                    nn.Linear(1024, 256, bias=False),\
                    nn.ReLU(),\
                    nn.Linear(256, dense_out, bias=False),\
                    nn.Sigmoid()\
                    )


        self.optimizer = torch.optim.Adam(self.predictor.parameters(),\
                lr=self.learning_rate)

    def set_grad(self):

        

        for param in self.predictor.parameters():
            param.requires_grad = True


    def set_no_grad(self):



        for param in self.predictor.parameters():
            param.requires_grad = False

    def update_predictor(self, loss):

        loss.backward()

        self.optimizer.step()

    def get_bonus(self, obs):

        prediction = self.forward(obs)

        loss = torch.mean(torch.abs((obs-prediction)**2),\
                dim=[1,2,3])

        # loss is a tensor used for vectorized rnd reward bonuses
        return loss

    def get_bonus_update(self, obs):

        self.predictor.zero_grad()

        # loss is a tensor used for vectorized rnd reward bonuses
        loss = self.get_bonus(obs)

        # update loss is a scalar used for backprop
        update_loss = torch.mean(loss)

        self.update_predictor(update_loss)

        return loss

    def get_bonus_accumulate(self, obs):

        if self.buffer_length == 0:
            self.predictor.zero_grad()
            self.accumulate_loss = 0.0

        loss = self.get_bonus(obs)

        self.accumulate_loss += torch.mean(loss)

        self.buffer_length += 1

        if self.buffer_length >= self.batch_size:
            self.accumulate_loss = self.accumulate_loss / self.batch_size

            self.update_predictor(self.accumulate_loss)

            self.buffer_length = 0

        return loss


    def get_bonus_only(self, obs):

        with torch.no_grad():

            loss = self.get_bonus(obs)

        return loss

class PredictionBonus(AE2D):

    def __init__(self, env, **kwargs):
        super(PredictionBonus, self).__init__(env, **kwargs)

        self.learning_rate = 3e-4

        self.my_name = "PredictionBonus"

        self.prediction_steps = 5

        self.grid_buffer = []


    def forward(self, obs):

        prediction = self.predictor(obs)

        prediction = prediction.reshape(\
                self.inner_env.instances, 1, self.inner_env.height, self.inner_env.width)

        return prediction

    def get_bonus(self, obs):

        self.grid_buffer.append(obs)

        #loss = torch.zeros(obs.shape[0]).to(self.my_device)

        #for step in range(1, len(self.grid_buffer)):

        # feed frame to model
        prediction = self.forward(self.grid_buffer[0])
        # target is the next frame
        my_target = self.grid_buffer[-1]

        loss = torch.mean(torch.abs((my_target-prediction)**2),\
                dim=[1,2,3]) #+ my_target.mean(dim=[1,2,3])

        if len(self.grid_buffer) > self.prediction_steps:
            _ = self.grid_buffer.pop(0)

        # loss is a tensor used for vectorized rnd reward bonuses

        #if len(self.grid_buffer) < self.prediction_steps:
        #    loss += torch.tensor([1.0]).to(self.my_device)

        return loss



    def get_bonus_update(self, obs):

        self.predictor.zero_grad()

        # loss is a tensor used for vectorized rnd reward bonuses
        loss = self.get_bonus(obs)

        # update loss is a scalar used for backprop
        update_loss = torch.mean(loss)

        self.update_predictor(update_loss)

        return loss

    def get_bonus_accumulate(self, obs):

        if self.buffer_length == 0:
            self.predictor.zero_grad()
            self.accumulate_loss = 0.0

        loss = self.get_bonus(obs)

        self.accumulate_loss += torch.mean(loss)

        self.buffer_length += 1

        if self.buffer_length >= self.batch_size:
            self.accumulate_loss = self.accumulate_loss / self.batch_size

            self.update_predictor(self.accumulate_loss)

            self.buffer_length = 0

        return loss

    def get_bonus_update(self, obs):

        self.predictor.zero_grad()

        # loss is a tensor used for vectorized rnd reward bonuses
        loss = self.get_bonus(obs)

        # update loss is a scalar used for backprop
        update_loss = torch.mean(loss)

        self.update_predictor(update_loss)

        return loss

    def get_bonus_accumulate(self, obs):

        if self.buffer_length == 0:
            self.predictor.zero_grad()
            self.accumulate_loss = 0.0

        loss = self.get_bonus(obs)

        self.accumulate_loss += torch.mean(loss)

        self.buffer_length += 1

        if self.buffer_length >= self.batch_size:
            self.accumulate_loss = self.accumulate_loss / self.batch_size

            self.update_predictor(self.accumulate_loss)

            self.buffer_length = 0

        return loss.detach()

    def step(self, action):

        action = action.to(self.inner_env.my_device)
        obs, reward, done, info = self.env.step(action)

        prediction_bonus = self.get_bonus_accumulate(obs).unsqueeze(1)

        bonus = (0.1 -  prediction_bonus) #+ (obs.mean(dim=[1,2,3]) )
        my_mean = obs.mean(dim=[1,2,3])

        for ii in range(my_mean.shape[0]):
            if my_mean[ii] == 0.0:
                bonus[ii] *= 0.0


        reward += self.reward_scale * bonus


        self.live_cells = obs.sum()

        return obs, reward, done, info

class SurpriseBonus(AE2D):

    def __init__(self, env, **kwargs):
        super(SurpriseBonus, self).__init__(env, **kwargs)

        self.ca_steps = 3

    def step(self, action):

        action = action.to(self.inner_env.my_device)
        obs, reward, done, info = self.env.step(action)

        prediction_bonus = self.get_bonus_accumulate(obs).unsqueeze(1)

        bonus = prediction_bonus #+ (obs.mean(dim=[1,2,3]) )
        my_mean = obs.mean(dim=[1,2,3])

        for ii in range(my_mean.shape[0]):
            if my_mean[ii] == 0.0:
                bonus[ii] *= 0.0


        reward += self.reward_scale * bonus


        self.live_cells = obs.sum()

        return obs, reward, done, info

class SpeedDetector(Motivator):

    def __init__(self, env, **kwargs):
        super(SpeedDetector, self).__init__(env, **kwargs)

        self.reward_scale = 1.0

        self.center_of_mass = None 

        self.speed_modulator = 32.0

        self.mass_weight_w = torch.arange(self.inner_env.height)\
                .reshape(1, -1).to(self.my_device)
        self.mass_weight_h = torch.arange(self.inner_env.width)\
                .reshape(-1, 1).to(self.my_device)

        # make a mass to exclude the action area: gliders/mobility is only 
        # rewarded outside of it. 

        action_mask = torch.ones(1, 1, \
                self.action_height, self.action_width).to(self.my_device)

        action_mask = self.inner_env.action_padding(action_mask)

        action_mask = torch.ones_like(action_mask) - action_mask

        # mask the center of mass matrices
        self.mass_weight_h = self.mass_weight_h * action_mask
        self.mass_weight_w = self.mass_weight_w * action_mask

        self.growing_steps = 0
        self.smooth_velocity = None
        self.speed = None

        self.velocity = torch.tensor([self.inner_env.instances, 1, 0., 0.])\
                .to(self.my_device)

        self.live_cells = None

    def step(self, action):

        obs, reward, done, info = self.env.step(action)

        live_cells = torch.sum(self.inner_env.universe, dim=[1,2,3])
        

        center_of_mass_h = torch.sum(obs * self.mass_weight_h, dim=[1,2,3]) \
                / (live_cells + 1e-7)
        center_of_mass_w = torch.sum(obs * self.mass_weight_w, dim=[1,2,3]) \
                / (live_cells + 1e-7)

        center_of_mass = torch.cat([center_of_mass_h.unsqueeze(0), \
                center_of_mass_w.unsqueeze(0)])

        if self.center_of_mass is None:
            self.center_of_mass = center_of_mass
        else:
            velocity = self.center_of_mass - center_of_mass

            speed = torch.sqrt(torch.sum(torch.pow(velocity, 2)))

            self.speed = speed
            self.velocity = velocity
            self.center_of_mass = center_of_mass

            reward += speed

        self.live_cells = live_cells

        return obs, reward, done, info


        

class PufferDetector(Motivator):

    """
    This wrapper detects unbounded growth patterns in the absence of agent actions.
    Due to the simplicity of the detection logic, it will also detect glider/spaceship guns
    and naturally ocurring growth (i.e. growth due to growing rulesets like B3/45678.

    In cases where growth is naturally ocurring, this wrapper would  
    """

    def __init__(self, env, **kwargs):
        super(PufferDetector, self).__init__(env, **kwargs) 

        self.my_name = "PufferDetector"

        self.cells = []
        self.live_cells = 0.0
        self.reward_scale = 1.0
        
        # growth threshold is also used to calculate the exponential average num live cells
        self.growth_threshold = 512

        self.growing_steps = 0
    
    def step(self, action):

        obs, reward, done, info = self.env.step(action)

        self.live_cells = torch.sum(self.inner_env.universe).cpu().numpy() 

        
        if not(torch.sum(action)):

            self.cells.append(self.live_cells)

            if len(self.cells) > self.growth_threshold:
                slope = self.cells[-1] - self.cells[0]

                self.cells.pop(0)
                if slope > 0.01:
                    reward += 1


        else:
            self.growing_steps = 0
            self.cells = []
        

        
        return obs, reward, done, info

def get_symmetric_action(probability=0.125, vertical_symmetry=False):
    
    action = torch.zeros(0,0,64,64)
    midpoint = action.shape[3] // 2
    
    for ii in range(action.shape[2]):
        for jj in range(1, midpoint):
            
            if torch.rand(1) <= probability:
                if jj > 1:
                    
                    action[:,:,ii,midpoint+jj] = 1.0
                    action[:,:,ii,midpoint-jj] = 1.0
            
    
    return action

def get_glider():
    action = torch.zeros(1,1,64,64)
    action[:,:,32,32] = 1.0
    action[:,:,33,32:34] = 1.0
    action[:,:, 34, 31] = 1.0
    action[:,:, 34, 33] = 1.0
    
    return action

def get_morley_puffer():
    action = torch.zeros(1,1,64,64)
    action[:,:,31:33,32] = 1.0
    action[:,:,30,33] = 1.0
    action[:,:,33,33] = 1.0
    
    action[:,:,29:35,34] = 1.0
    
    action[:,:,30,35:37] = 1.0
    action[:,:,33,35:37] = 1.0
    action[:,:,31:33,37] = 1.0
    
    return action

if __name__ == "__main__":


    env = CARLE() 
    env = PredictionBonus(env)
    env = ParsimonyBonus(env)
    #env = SpeedDetector(env)

    #rules for Life
    env.inner_env.birth = [3]
    env.inner_env.survive = [2,3]

    action_fn = get_morley_puffer

    for action_fn in [get_glider]: #, get_morley_puffer, get_symmetric_action]:

        obs = env.reset()
        sum_reward = 0.0
        rewards = []
        cells = []
        
        action = action_fn()

        for step in range(1024):
            # action (glider, then no toggles)
            # sets up predictable sequence
            # bonus should go up

            obs, reward, d, i = env.step(action)
            rewards.append(reward)
            
            env.live_cells = obs.sum()
            cells.append(env.live_cells)

            action *= 0.0

            sum_reward += reward

        for step in range(512):

            # random action, predictability reward should plummet

            action = (torch.rand_like(action) > 0.95).float()
            obs, reward, d, i = env.step(action)
            rewards.append(reward)
            
            cells.append(env.live_cells)


            sum_reward += reward
        print("reward sum ", sum_reward)
        
        plt.figure()
        plt.plot(rewards, lw=4, label="rewards")
        #plt.plot(cells, label = "live cells")

        plt.legend()

        plt.figure()

        plt.imshow(obs[0].detach().squeeze())


        
    plt.show()
