"""GET /api/v1/rubrics"""

from __future__ import annotations

from flask import Blueprint, jsonify

from validation.rubric_loader import get_rubric

rubrics_bp = Blueprint("rubrics", __name__)


@rubrics_bp.route("/rubrics", methods=["GET"])
def rubrics():
    rubric = get_rubric()
    return (
        jsonify(
            {
                "rubric_title": rubric.title,
                "rubric_version": rubric.version,
                "framework": rubric.framework,
                "dimensions": [
                    {"rubric_id": d.id, "name": d.name, "weight": d.weight}
                    for d in rubric.rubrics
                ],
            }
        ),
        200,
    )
