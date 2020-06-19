#!/bin/bash

# if force == true, then new config file will overwrite original files.
force=false

mkdir -p ~/.config/pip
mkdir -p ~/software
if [ $force == true ]; then
    prefix="-f"
else
    prefix=""
fi
ln -s ${prefix} $(pwd)/config/pip.conf ~/.config/pip
ln -s ${prefix} $(pwd)/config/vimrc ~/.vimrc
ln -s ${prefix} $(pwd)/config/proxychains.conf ~/proxychains.conf
ln -s ${prefix} $(pwd)/config/shadowsocks.json ~/shadowsocks.json
ln -s ${prefix} $(pwd)/config/gitconfig ~/.gitconfig
ln -s ${prefix} $(pwd)/config/tmux.conf ~/.tmux.conf
ln -s ${prefix} $(pwd)/config/zshrc ~/.zshrc

git clone https://github.com/VundleVim/Vundle.vim.git ~/.vim/bundle/Vundle.vim
git clone git://github.com/robbyrussell/oh-my-zsh.git ~/.oh-my-zsh
git clone https://github.com/tmux-plugins/tmux-prefix-highlight.git ~/software
echo "Please run PluginInstall command in vim manually"
echo "Please run ~/.oh-my-zsh/tools/install.sh"

