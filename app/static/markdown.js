const markdown = window.markdownit({ html: false });

// Render the task-list markers used in the session template as read-only checkboxes.
markdown.core.ruler.after("inline", "task_lists", ({ tokens }) => {
  for (let index = 2; index < tokens.length; index += 1) {
    const item = tokens[index - 2];
    const paragraph = tokens[index - 1];
    const inline = tokens[index];
    const text = inline.children?.[0];
    if (item.type !== "list_item_open" || paragraph.type !== "paragraph_open" || text?.type !== "text") continue;

    const marker = inline.content.match(/^\[([ xX])\](?:[ \t]+|$)/);
    if (!marker) continue;
    item.attrJoin("class", "task-list-item");
    text.content = text.content.slice(marker[0].length);
    const checkbox = new inline.constructor("task_checkbox", "input", 0);
    checkbox.meta = { checked: marker[1] !== " " };
    inline.children.unshift(checkbox);
  }
});

markdown.renderer.rules.task_checkbox = (tokens, index) => {
  const checked = tokens[index].meta.checked;
  return checked
    ? '<input type="checkbox" disabled checked aria-label="Completed"> '
    : '<input type="checkbox" disabled aria-label="Incomplete"> ';
};

const renderImage = markdown.renderer.rules.image;
markdown.renderer.rules.image = (tokens, index, options, env, renderer) => {
  tokens[index].attrSet("loading", "lazy");
  tokens[index].attrSet("referrerpolicy", "no-referrer");
  return renderImage(tokens, index, options, env, renderer);
};
