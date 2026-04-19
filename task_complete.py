with open("/Users/ispielma/.gemini/antigravity/brain/437925c8-085f-4140-b319-903ac8791607/task.md", "r") as f:
    text = f.read()

text = text.replace("[ ]", "[x]")

with open("/Users/ispielma/.gemini/antigravity/brain/437925c8-085f-4140-b319-903ac8791607/task.md", "w") as f:
    f.write(text)
