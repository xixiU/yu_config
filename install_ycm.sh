#!/bin/bash

# from https://github.com/ycm-core/YouCompleteMe#linux-64-bit
sudo apt install build-essential cmake vim python3-dev
cd ~/.vim/bundle/YouCompleteMe
python3 install.py
