"""Projection on the frozen signed, nonuniform victory-loss support plus absorbing death."""
import torch
from panel5e import FIVE
from value import CENTERS

def deposit(amount,locations):
    """Linearly distribute masses over the two adjacent centers, saturating outer tails."""
    centers=locations.new_tensor(CENTERS)
    x=locations.clamp(centers[0],centers[-1])
    upper=torch.searchsorted(centers,x.contiguous()).clamp(1,len(CENTERS)-1)
    lower=upper-1
    frac=(x-centers[lower])/(centers[upper]-centers[lower])
    result=amount.new_zeros((len(amount),len(centers)))
    result.scatter_add_(1,lower,amount*(1-frac))
    result.scatter_add_(1,upper,amount*frac)
    outside=(amount*((locations<centers[0])|(locations>centers[-1]))).sum(1)
    return result,outside

def terminal_target(hp,end,dead):
    loss=(hp-end).to(torch.float32).reshape(-1,1)
    if ((loss.abs().squeeze(1)>CENTERS[-1])&~dead).any():raise ValueError("Terminal loss outside support")
    masses,_=deposit((~dead).float().reshape(-1,1),loss)
    return torch.cat([dead.float()[:,None],masses],1)

def temporal_target(successor_prob,hp,next_hp):
    centers=successor_prob.new_tensor(CENTERS)
    shift=(hp-next_hp).to(successor_prob.dtype)
    result,overflow=deposit(successor_prob[:,1:],centers[None,:]+shift[:,None])
    return torch.cat([successor_prob[:,:1],result],1),overflow
