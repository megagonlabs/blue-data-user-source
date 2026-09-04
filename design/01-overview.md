# UDb — Overview

## Objective

In an agentic platform, the user is a dynamic and continuously evolving source of information. User interactions — including conversations, uploaded files, and other forms of input — may contain valuable signals that reveal structured data such as user preferences, background, context, goals, and environment. Extracting, storing, and retrieving this information when needed is essential to building agents that understand and adapt to the people they serve.

## What UDb Does

UDb provides a standardized framework to capture and manage this information. Specifically, it enables the platform to:

- Extract structured user information from various data sources, including interactions in a session, files uploaded, etc.
- Persistently store and manage user-related data, metadata, and data sources
- Allow agents to retrieve relevant user data when queried as structured data
- Interact with users to obtain missing or incomplete user data 
- Maintain a structured and evolving representation of user data across sessions

## Design Philosophy

By formalizing UDb as a database system, this framework allows agents to access and utilize user data in the same way they interact with traditional databases such as PostgreSQL or MongoDB. Internally, UDb will have components analogous to those found in conventional database systems where appropriate, and introduce new components specific to the challenges of managing user knowledge in an agentic context.
