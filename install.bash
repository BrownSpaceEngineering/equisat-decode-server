#!/usr/bin/env bash
git submodule init
git submodule update
pip install -r requirements.txt
sudo apt install nginx
sudo rm /etc/nginx/sites-enabled/default
sudo cp decoder.brownspace.org.conf /etc/nginx/sites-available/
sudo ln -s /etc/nginx/sites-available/decoder.brownspace.org.conf /etc/nginx/sites-enabled/decoder.brownspace.org.conf