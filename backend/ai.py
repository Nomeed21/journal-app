"""Shared AI client."""
import os

from groq import Groq

groq_client = Groq(api_key=os.environ["GROQ_API_KEY"])
