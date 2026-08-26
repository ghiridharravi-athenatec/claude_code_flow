function CriteriaList({ dimensionResults }) {
  return (
    <table className="criteria-list">
      <thead>
        <tr>
          <th>Dimension</th>
          <th>Weight</th>
          <th>Score</th>
          <th>Points</th>
          <th>Matched level</th>
          <th>Evidence</th>
        </tr>
      </thead>
      <tbody>
        {dimensionResults.map((dimension) => (
          <tr key={dimension.rubric_id}>
            <td>
              {dimension.rubric_id} - {dimension.name}
              {dimension.hard_rule_triggered && (
                <span className="hard-rule-badge"> [{dimension.hard_rule_triggered}]</span>
              )}
            </td>
            <td>{dimension.weight}</td>
            <td>{dimension.score}</td>
            <td>{dimension.points_earned}</td>
            <td>{dimension.matched_level_text}</td>
            <td>{dimension.matched_snippet || "—"}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export default CriteriaList;
