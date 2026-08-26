function ResultsSummary({ result }) {
  const { overall, record_filename: recordFilename } = result;

  return (
    <div className={`results-summary decision-${overall.decision.replace(/\s+/g, "-").toLowerCase()}`}>
      <h2>{recordFilename}</h2>
      <p className="overall-score">
        {overall.score_points} / {overall.score_max}
      </p>
      <p className="overall-decision">{overall.decision}</p>
      <p className="overall-note">{overall.decision_note}</p>

      {overall.hard_rules_triggered.length > 0 && (
        <div className="hard-rules-triggered">
          <h3>Hard rules triggered</h3>
          <ul>
            {overall.hard_rules_triggered.map((rule) => (
              <li key={rule.id}>
                <strong>{rule.id}</strong> ({rule.rubric_id}): {rule.action} - {rule.reason}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

export default ResultsSummary;
