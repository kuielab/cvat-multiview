#!/usr/bin/env python3
"""
Test pre-annotation editing with real dataset (multisensor_home2_01-00-Part1)
Verifies that editing one shape does NOT affect other shapes.
"""
import requests
import sys

host = "http://localhost:8080"

def login():
    session = requests.Session()
    session.get(f"{host}/api/auth/login", timeout=10)
    csrf = session.cookies.get("csrftoken")
    headers = {"X-CSRFToken": csrf} if csrf else {}
    session.post(f"{host}/api/auth/login", json={"username": "admin", "password": "admin123"}, headers=headers, timeout=10)
    return session

def get_annotations(session, job_id=2):
    h = {"X-CSRFToken": session.cookies.get("csrftoken", "")}
    resp = session.get(f"{host}/api/jobs/{job_id}/annotations", headers=h, timeout=30)
    return resp.json().get("shapes", [])

def update_shape(session, job_id, shape, new_points=None, new_rotation=None):
    h = {"X-CSRFToken": session.cookies.get("csrftoken", ""), "Content-Type": "application/json"}
    update = {
        "id": shape["id"],
        "frame": shape["frame"],
        "points": new_points if new_points else shape["points"],
        "type": "rectangle",
        "label_id": shape["label_id"],
        "occluded": shape.get("occluded", False),
        "z_order": shape.get("z_order", 0),
        "rotation": new_rotation if new_rotation is not None else shape.get("rotation", 0.0),
        "view_id": shape.get("view_id"),
        "attributes": shape.get("attributes", []),
    }
    payload = {"version": 0, "tags": [], "shapes": [update], "tracks": []}
    resp = session.patch(f"{host}/api/jobs/{job_id}/annotations", params={"action": "update"}, json=payload, headers=h, timeout=30)
    return resp.status_code

def build_baseline(shapes):
    return {s["id"]: {"frame": s["frame"], "points": s["points"][:], "label_id": s["label_id"], "view_id": s.get("view_id")} for s in shapes}

def verify_others(target_ids, baseline, post_shapes):
    """Count shapes that changed unexpectedly (not in target_ids)"""
    changed = 0
    for s in post_shapes:
        if s["id"] in target_ids:
            continue
        if s["id"] in baseline:
            orig = baseline[s["id"]]
            if s["points"] != orig["points"] or s["frame"] != orig["frame"]:
                changed += 1
    return changed

def run_test(name, session, job_id, targets, new_points_list, new_rotation=None):
    """
    Generic test: edit target shapes, verify others unchanged, then restore.
    targets: list of shape dicts
    new_points_list: list of new points (or None to keep same) per target
    """
    shapes = get_annotations(session, job_id)
    bl = build_baseline(shapes)

    target_ids = set()
    for t, np in zip(targets, new_points_list):
        rot = new_rotation if new_rotation is not None else None
        update_shape(session, job_id, t, new_points=np, new_rotation=rot)
        target_ids.add(t["id"])

    post = get_annotations(session, job_id)
    changed = verify_others(target_ids, bl, post)

    all_targets_ok = True
    for t, np in zip(targets, new_points_list):
        expected_pts = np if np else t["points"]
        found = any(s["id"] == t["id"] and s["points"] == expected_pts for s in post)
        if not found:
            all_targets_ok = False

    ok = changed == 0 and all_targets_ok and len(post) == 75
    status = "PASS" if ok else "FAIL"
    print(f"[{status}] {name} (changed={changed}, targets_ok={all_targets_ok}, count={len(post)})")

    # Restore
    for t in targets:
        update_shape(session, job_id, t, new_points=bl[t["id"]]["points"])

    return ok

def main():
    session = login()
    print("[OK] Logged in")

    shapes = get_annotations(session)
    print(f"Total shapes: {len(shapes)}")
    if len(shapes) != 75:
        print(f"ERROR: Expected 75 shapes, got {len(shapes)}")
        sys.exit(1)

    passed = 0
    failed = 0

    # Helper to find shapes
    def find(frame, view_id):
        return [s for s in shapes if s["frame"] == frame and s.get("view_id") == view_id][0]

    # TC01: Move Enter/view0 on frame 20
    t = find(20, 0)
    if run_test("TC01: Move Enter/view0 frame 20 (+100)", session, 2, [t], [[p+100 for p in t["points"]]]):
        passed += 1
    else:
        failed += 1

    # TC02: Move OpenCurtain/view2 on frame 714
    t = find(714, 2)
    if run_test("TC02: Move OpenCurtain/view2 frame 714 (-200)", session, 2, [t], [[p-200 for p in t["points"]]]):
        passed += 1
    else:
        failed += 1

    # TC03: Move Sitdown/view4 to corner
    t = find(1173, 4)
    if run_test("TC03: Move Sitdown/view4 frame 1173 to corner", session, 2, [t], [[50.0, 50.0, 250.0, 250.0]]):
        passed += 1
    else:
        failed += 1

    # TC04: Resize UseLaptop/view1 (enlarge)
    t = find(2112, 1)
    if run_test("TC04: Resize UseLaptop/view1 frame 2112", session, 2, [t], [[800.0, 400.0, 1200.0, 700.0]]):
        passed += 1
    else:
        failed += 1

    # TC05: Rotate TurnOnLamp/view3 (45 deg)
    shapes = get_annotations(session)
    bl = build_baseline(shapes)
    t = find(258, 3)
    update_shape(session, 2, t, new_rotation=45.0)
    post = get_annotations(session)
    changed = verify_others({t["id"]}, bl, post)
    rotated = any(s["id"] == t["id"] and s.get("rotation", 0) == 45.0 for s in post)
    ok = changed == 0 and rotated and len(post) == 75
    print(f"[{'PASS' if ok else 'FAIL'}] TC05: Rotate TurnOnLamp/view3 frame 258 (45 deg) (changed={changed})")
    if ok:
        passed += 1
    else:
        failed += 1
    update_shape(session, 2, t, new_rotation=0.0)

    # TC06: Sequential edit 3 shapes on different frames
    t1, t2, t3 = find(20, 0), find(714, 0), find(1254, 0)
    if run_test("TC06: Sequential edit 3 shapes (frames 20,714,1254)", session, 2,
                [t1, t2, t3],
                [[100, 100, 200, 200], [300, 300, 400, 400], [500, 500, 600, 600]]):
        passed += 1
    else:
        failed += 1

    # TC07: Edit all 5 views on frame 591
    f591 = [find(591, v) for v in range(5)]
    pts = [[100*(i+1), 100*(i+1), 100*(i+1)+100, 100*(i+1)+100] for i in range(5)]
    if run_test("TC07: Edit 5 views on same frame (591)", session, 2, f591, pts):
        passed += 1
    else:
        failed += 1

    # TC08: Cross-label edit (Enter, Sitdown, UseLaptop)
    ct = [find(104, 0), find(1149, 0), find(1683, 0)]
    if run_test("TC08: Cross-label edit (Enter/Sitdown/UseLaptop)", session, 2,
                ct, [[0, 0, 50, 50], [1800, 1000, 1920, 1080], [500, 250, 700, 450]]):
        passed += 1
    else:
        failed += 1

    # TC09: Full frame bbox
    t = find(837, 0)
    if run_test("TC09: Full frame bbox (0,0,1920,1080)", session, 2, [t], [[0.0, 0.0, 1920.0, 1080.0]]):
        passed += 1
    else:
        failed += 1

    # TC10: Tiny resize (+1px)
    t = find(1196, 0)
    if run_test("TC10: Tiny resize (+1px)", session, 2, [t], [[p+1 for p in t["points"]]]):
        passed += 1
    else:
        failed += 1

    print(f"\n{'='*60}")
    print(f"SUMMARY: {passed} passed, {failed} failed, {passed+failed} total")
    print(f"{'='*60}")
    if failed == 0:
        print("ALL TESTS PASSED - Real dataset pre-annotations properly isolated!")
    else:
        print(f"FAILURES DETECTED: {failed} tests failed")
    sys.exit(0 if failed == 0 else 1)

if __name__ == "__main__":
    main()
