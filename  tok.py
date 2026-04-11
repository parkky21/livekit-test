# from livekit import api
# agent_name="my-agent"
# def generate_token():
#     token = api.AccessToken(os.getenv('LIVEKIT_API_KEY'), os.getenv('LIVEKIT_API_SECRET')) \
#     .with_identity("identity") \
#     .with_name("name") \
#     .with_grants(api.VideoGrants(
#         room_join=True,
#         room="my-room",
#     ))

#     token = token.with_room_config(
#             api.RoomConfiguration(
#                 agents=[
#                     api.RoomAgentDispatch(
#                         agent_name=agent_name
#                     )
#                 ],
#             ),
#         )

#     token = token.to_jwt()
#     return token