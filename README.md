# Processors

Compare processors from cpubenchmark.net

## Motivation

When I was to decide for a new PC I wanted to compare multiple CPUs with each other.
Cpubenchmark.net at that time allowed to compare 3 CPUs, which was not sufficient for my needs.

## USE

1. Install required dependencies: `pip install -r requirements.txt`
2. Run `./processors.py`

## Develop

Additionally to the steps in USE:

1. Install dev dependencies: `pip install -r requrements-dev.txt`
2. Init pre-commit: `pre-commit install`

## Current issues

The script ends with a bunch of HTTP 403 messages, this might be due to the nature of this script
