#!/bin/bash
eval "$(conda shell.bash hook)"
conda activate interview-agent

# Run session 1 for user Shayan
python3 src/main.py --mode terminal --user_id Shayan --restart
