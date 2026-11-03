"""Generic UI-tree text scanning helpers for DaVinci label discovery."""


def find_first_text(
    root,
    target_text,
    *,
    get_element_text_fn,
    get_element_children_fn,
    max_depth=30,
):
    target_texts = target_text if isinstance(target_text, set) else {target_text}

    def traverse(element, depth=0):
        if element is None or depth > max_depth:
            return None

        if get_element_text_fn(element) in target_texts:
            return element

        children = get_element_children_fn(element)
        if children:
            for child in children:
                found = traverse(child, depth + 1)
                if found is not None:
                    return found

        return None

    return traverse(root)


def collect_diagnostic_texts(
    root,
    *,
    get_element_text_fn,
    get_element_children_fn,
    limit=12,
    max_depth=20,
):
    texts = []

    def add_text(text):
        if text and text not in texts:
            texts.append(text)

    def traverse(element, depth=0):
        if element is None or depth > max_depth or len(texts) >= limit:
            return

        add_text(get_element_text_fn(element))

        children = get_element_children_fn(element)
        if children:
            for child in children:
                traverse(child, depth + 1)

    traverse(root)
    return texts


__all__ = ['collect_diagnostic_texts', 'find_first_text']
