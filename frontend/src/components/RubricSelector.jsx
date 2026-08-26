// Named "Selector" to match CLAUDE.md's fixed directory structure, but per
// SPEC.md Section 4.2 there is exactly one active rubric and no selection
// step in v1 -- this displays which rubric is active rather than letting
// the user choose one.

function RubricSelector({ rubric }) {
  if (!rubric) {
    return null;
  }

  return (
    <div className="rubric-info">
      <h2>{rubric.rubric_title}</h2>
      <p>
        Version {rubric.rubric_version} &middot; {rubric.framework}
      </p>
      <p className="rubric-dimension-count">{rubric.dimensions.length} scored dimensions</p>
    </div>
  );
}

export default RubricSelector;
