const groupNameCollator = new Intl.Collator("ru", {
  numeric: true,
  sensitivity: "base",
});

export function sortGroupsByName(groups) {
  return [...(groups || [])].sort((firstGroup, secondGroup) =>
    groupNameCollator.compare(firstGroup.course_name || "", secondGroup.course_name || ""),
  );
}
