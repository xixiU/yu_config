#!/bin/bash

sudo cp /etc/apt/sources.list /etc/apt/sources.list.bak
sudo cp ./config/sources.list /etc/apt/sources.list

sudo apt update
sudo apt install --yes tmux proxychains git vim zsh tree ctags
pip install https://github.com/shadowsocks/shadowsocks/archive/master.zip -U

echo "Anaconda installation package can be downloaded from tsinghua mirror website"
