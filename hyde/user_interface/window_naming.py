def next_numbered_name(prefix, existing_names, counter=0):
    existing = {str(name) for name in existing_names}
    current = int(counter)
    candidate = f"{prefix}{current}"
    while candidate in existing:
        current += 1
        candidate = f"{prefix}{current}"
    return candidate, current + 1
