from services.costing import compute_costs


def test_rework_recoat_is_flat_fee_regardless_of_item():
    result = compute_costs("Rework / Recoat", 3, item=None)
    assert result.material_cost == 132
    assert result.qty_to_remove is None


def test_replace_part_uses_std_cost_times_qty_to_remove():
    item = {"rule": 2, "std_cost": 10}
    result = compute_costs("Replace Part", 3, item=item)
    assert result.qty_to_remove == 6
    assert result.material_cost == 60


def test_unmatched_product_code_has_no_cost_except_rework_flat_fee():
    result = compute_costs("Replace Part", 3, item=None)
    assert result.qty_to_remove is None
    assert result.material_cost is None
    assert result.total_cost == 0


def test_scrap_entire_door_is_costed_like_replace_part():
    item = {"rule": 1, "std_cost": 450}
    result = compute_costs("Scrap Entire Door", 1, item=item)
    assert result.material_cost == 450


def test_pieces_share_of_job_material():
    # 1 length on the job, door has 2 stiles, scrapping 1 -> write off half.
    item = {"rule": 1, "std_cost": 10}
    r = compute_costs("Replace Part", 1, item, job_material_qty=1, pieces_per_door=2)
    assert r.qty_to_remove == 0.5 and r.material_cost == 5.0
    r = compute_costs("Replace Part", 2, item, job_material_qty=1, pieces_per_door=2)
    assert r.qty_to_remove == 1.0


def test_pieces_unset_falls_back_to_rule():
    item = {"rule": 0.5, "std_cost": 10}
    r = compute_costs("Replace Part", 2, item, job_material_qty=1, pieces_per_door=None)
    assert r.qty_to_remove == 1.0
