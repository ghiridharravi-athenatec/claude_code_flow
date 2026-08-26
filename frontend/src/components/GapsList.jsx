function GapsList({ flaggedGaps }) {
  if (flaggedGaps.length === 0) {
    return <p className="no-gaps">No flagged gaps -- every dimension scored 3 or higher.</p>;
  }

  return (
    <div className="gaps-list">
      <h3>Flagged gaps</h3>
      <ul>
        {flaggedGaps.map((gap) => (
          <li key={gap.rubric_id}>
            {gap.rubric_id} - {gap.name} (weight {gap.weight}): scored {gap.score}
          </li>
        ))}
      </ul>
    </div>
  );
}

export default GapsList;
