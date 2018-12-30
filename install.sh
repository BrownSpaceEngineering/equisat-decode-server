#!/usr/bin/env bash
pip install -r requirements.txt
sudo apt install nginx
cp decoder.brownspace.org.conf /etc/nginx/sites-available/
ln -s /etc/nginx/sites-available/decoder.brownspace.org.conf /etc/nginx/sites-enabled/decoder.brownspace.org.conf