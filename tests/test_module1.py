import copy
import json
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "backend" / "module1"))
sys.path.insert(0, str(REPO / "integration"))
from module1_core import Module1, DomainError, load_stage, validate_resources, verify_envelope, validator
from run_module1 import run
from storage import SoldierStore
from server import create_server
from module2_mock import create_mock
from http_support import JsonHandler, serve
from module2_client import Module2Client
generator = load_stage("02_generate_synthetic_soldiers.py")


def sample(**updates):
    row = {"soldier_id": "22-00000001", "is_synthetic": True, "age": 23,
           "age_basis": "calendar_year_minus_birth_year", "sex": "male",
           "role": "infantry_rifleman", "height_cm": 175, "weight_kg": 75,
           "combat_load_kg": 15, "pushups_2min": 48, "situps_2min": 60,
           "run_3km_seconds": 960, "pushups_duration_seconds": 120,
           "situps_duration_seconds": 120, "run_distance_m": 3000, "baseline_test_load_kg": 0}
    row.update(updates)
    return row


def http(base, path, body=None, raw=None, headers=None):
    data = json.dumps(body).encode() if body is not None else raw
    request = urllib.request.Request(base + path, data=data,
                                    headers=headers or {"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


class Running:
    def __init__(self, server):
        self.server = server
        self.thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": .02}, daemon=True)
        self.base = f"http://127.0.0.1:{server.server_port}"

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *args):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)


class CoreTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = Module1()

    def test_exact_difference(self):
        result, _ = self.engine.evaluate(sample())
        self.assertEqual(result["difference_matrix"], [[16, 18, -148, 0]])
        self.assertEqual(result["now_matrix"], [[48, 60, 960, .2]])
        self.assertEqual(result["goal_matrix"], [[64, 78, 812, .2]])
        self.assertEqual(result["profile"]["bmi"], 24.49)
        self.assertEqual(result["training_context"]["status"], "not_collected")

    def test_age_boundaries(self):
        for age, expected in [(18, [64,78,812]),(25,[64,78,812]),(26,[62,76,832]),(29,[62,76,832])]:
            with self.subTest(age=age):
                result, _ = self.engine.evaluate(sample(age=age))
                self.assertEqual(result["goal_matrix"][0][:3], expected)
        for age in [17,30]:
            with self.assertRaises(DomainError):
                self.engine.evaluate(sample(age=age))

    def test_goal_is_fixed_even_when_already_better(self):
        result, _ = self.engine.evaluate(sample(pushups_2min=90, situps_2min=100, run_3km_seconds=700))
        self.assertEqual(result["goal_matrix"], [[64,78,812,.2]])
        self.assertEqual(result["difference_matrix"], [[-26,-22,112,0]])
        self.assertEqual(result["goal_records"], result["reference_records"])
        self.assertEqual(result["current_records"]["pushups_2min"],90)
        verify_envelope(self.engine.envelope(result,"above-reference"))

    def test_fixed_goal_for_mixed_and_equal_records(self):
        for age, current, expected_goal, expected_difference in [
            (25, [90,60,700], [64,78,812,.2], [-26,18,112,0]),
            (26, [40,100,1000], [62,76,832,.2], [22,-24,-168,0]),
            (29, [62,76,832], [62,76,832,.2], [0,0,0,0]),
        ]:
            with self.subTest(age=age):
                result,_=self.engine.evaluate(sample(age=age,pushups_2min=current[0],
                                                     situps_2min=current[1],run_3km_seconds=current[2]))
                self.assertEqual(result["goal_matrix"],[expected_goal])
                self.assertEqual(result["difference_matrix"],[expected_difference])
                verify_envelope(self.engine.envelope(result,"mixed-reference"))

    def test_receiver_rejects_old_clamped_goal_and_contract(self):
        result,_=self.engine.evaluate(sample(pushups_2min=90,situps_2min=100,run_3km_seconds=700))
        envelope=self.engine.envelope(result,"old-clamping")
        bad=copy.deepcopy(envelope)
        bad["contract_version"]="1.0.0"
        with self.assertRaises(DomainError): verify_envelope(bad)
        p=envelope["module1_result"]
        p["goal_matrix"]=copy.deepcopy(p["now_matrix"])
        p["goal_records"]=p["current_records"].copy()
        p["difference_matrix"]=[[0,0,0,0]]
        with self.assertRaises(DomainError): verify_envelope(envelope)

    def test_load_is_auxiliary_and_bmi_recomputed(self):
        a, _ = self.engine.evaluate(sample(weight_kg=60,bmi=99))
        b, _ = self.engine.evaluate(sample(weight_kg=90))
        self.assertEqual(a["goal_records"], b["goal_records"])
        self.assertEqual(a["difference_matrix"][0][:3], b["difference_matrix"][0][:3])
        self.assertNotEqual(a["load_context"]["load_to_body_weight_ratio"], b["load_context"]["load_to_body_weight_ratio"])
        self.assertEqual(a["difference_matrix"][0][3], 0)
        self.assertFalse(a["load_context"]["readiness_assessed"])
        self.assertNotEqual(a["profile"]["bmi"], 99)

    def test_old_protocol_and_bad_ids_rejected(self):
        for changes in [{"pushups_1min":20},{"pushups_duration_seconds":60},{"soldier_id":"SYN-000001"},
                        {"soldier_id":"22-1234567"},{"soldier_id":"2022-12345678"},
                        {"soldier_id":"２２-12345678"},{"run_3km_seconds":float("nan")}]:
            with self.subTest(changes=changes), self.assertRaises(DomainError):
                self.engine.evaluate(sample(**changes))

    def test_duplicate_batch_no_computation(self):
        result=validator.validate_and_compute([sample(),sample()])
        self.assertEqual(result["records"],[])
        self.assertEqual(result["summary"]["computed_records"],0)

    def test_service_numbers_unique_and_configurable(self):
        a=generator.generate_records(1000,42,2022)
        b=generator.generate_records(1000,42,2022)
        self.assertEqual(a,b)
        self.assertEqual(a[0]["soldier_id"],"22-00000001")
        self.assertEqual(a[-1]["soldier_id"],"22-00001000")
        self.assertEqual(len({r["soldier_id"] for r in a}),1000)
        self.assertEqual(generator.generate_records(1,42,2026)[0]["soldier_id"],"26-00000001")
        for year in [22,2100,True]:
            with self.assertRaises(ValueError):
                generator.generate_records(1,42,year)

    def test_corrupt_resources_fail(self):
        for mutation in ("catalog_count","duplicate_id","evidence","range","age_overlap","duration","old_goal_policy"):
            resources=copy.deepcopy(self.engine.resources)
            catalog=resources["exercise_catalog"]
            if mutation=="catalog_count": catalog["exercises"].pop()
            if mutation=="duplicate_id": catalog["exercises"][1]["exercise_id"]=catalog["exercises"][0]["exercise_id"]
            if mutation=="evidence": catalog["exercises"][0]["evidence_ids"]=["missing"]
            if mutation=="range": catalog["exercises"][0]["frequency_per_week"]={"min":4,"max":1}
            if mutation=="age_overlap": resources["target_criteria"]["thresholds"][1]["age_min"]=25
            if mutation=="duration": resources["target_criteria"]["measurement_protocol"]["pushups_duration_seconds"]=60
            if mutation=="old_goal_policy": resources["target_criteria"]["goal_policy"]["pushups"]="max(now, reference)"
            with self.subTest(mutation=mutation),self.assertRaises(DomainError):
                validate_resources(resources)

    def test_contract_semantics(self):
        result,_=self.engine.evaluate(sample())
        envelope=self.engine.envelope(result,"test-request")
        self.assertEqual(verify_envelope(envelope),envelope)
        for mutate in ("delta","hash","version","shape","profile","protocol"):
            bad=copy.deepcopy(envelope)
            p=bad["module1_result"]
            if mutate=="delta": p["difference_matrix"][0][2]=148
            if mutate=="hash": p["resources_sha256"]="stale"
            if mutate=="version": p["versions"]["catalog"]="v0"
            if mutate=="shape": p["difference_matrix"].append([1,2,3,4])
            if mutate=="profile": p["profile"]["weight_kg"]=100
            if mutate=="protocol": p["measurement_protocol"]["pushups_duration_seconds"]=60
            with self.subTest(mutate=mutate),self.assertRaises(DomainError):
                verify_envelope(bad)

    def test_batch_failure_replaces_previous_success(self):
        with tempfile.TemporaryDirectory() as folder:
            directory=Path(folder); source=directory/"input.json"
            source.write_text(json.dumps([sample()]),encoding="utf-8")
            self.assertEqual(run(source,directory)["status"],"ready")
            source.write_text(json.dumps([sample(weight_kg=0)]),encoding="utf-8")
            self.assertEqual(run(source,directory)["status"],"failed")
            self.assertEqual(json.loads((directory/"module2_input.json").read_text(encoding="utf-8"))["records"],[])
            unchanged=source.read_bytes()
            with self.assertRaises(ValueError):
                run(directory/"module2_input.json",directory)
            self.assertEqual(source.read_bytes(),unchanged)


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.directory=Path(self.temp.name)
        self.seed=self.directory/"seed.json"
        generator.write_outputs(generator.generate_records(5,42),42,self.directory)
        self.seed=self.directory/"synthetic_soldiers.json"
        self.db=self.directory/"test.sqlite3"
        self.mock=Running(create_mock(0)).__enter__()
        self.api=Running(create_server(self.db,self.seed,self.mock.base,port=0,timeout=.15)).__enter__()

    def tearDown(self):
        self.api.__exit__()
        self.mock.__exit__()
        self.temp.cleanup()

    def test_full_flow_and_persistence(self):
        code,listing=http(self.api.base,"/api/v1/soldiers")
        self.assertEqual((code,listing["total"]),(200,5))
        code,created=http(self.api.base,"/api/v1/soldiers",sample())
        self.assertEqual(code,201)
        self.assertEqual(created["result"]["difference_matrix"],[[16,18,-148,0]])
        code,detail=http(self.api.base,"/api/v1/soldiers/22-00000001")
        self.assertEqual(detail["record"]["source"],"web")
        self.assertEqual(detail["result"],created["result"])
        code,ack=http(self.api.base,"/api/v1/soldiers/22-00000001/module2",{})
        self.assertEqual(code,200)
        self.assertEqual(ack["module2_response"]["mode"],"mock")
        self.assertIsNone(ack["module2_response"]["plan"])
        reopened=SoldierStore(self.db)
        self.assertEqual(reopened.seed_once(self.seed),0)
        self.assertEqual(reopened.list()["total"],6)
        self.assertEqual(reopened.get("22-00000001")["weight_kg"],75)
        with reopened.connect() as db:
            self.assertEqual(db.execute("SELECT status FROM deliveries").fetchone()[0],"accepted")

    def test_bad_input_and_duplicates_never_saved(self):
        for row in [sample(weight_kg=0),sample(pushups_duration_seconds=60),sample(soldier_id="bad"),{}]:
            code,_=http(self.api.base,"/api/v1/soldiers",row)
            self.assertEqual(code,422)
        self.assertEqual(http(self.api.base,"/api/v1/soldiers")[1]["total"],5)
        self.assertEqual(http(self.api.base,"/api/v1/soldiers",sample())[0],201)
        self.assertEqual(http(self.api.base,"/api/v1/soldiers",sample())[0],409)
        self.assertEqual(http(self.api.base,"/api/v1/soldiers")[1]["total"],6)

    def test_above_grade1_goal_survives_save_read_and_module2(self):
        row=sample(pushups_2min=90,situps_2min=100,run_3km_seconds=700)
        code,created=http(self.api.base,"/api/v1/soldiers",row)
        self.assertEqual(code,201)
        self.assertEqual(created["result"]["goal_matrix"],[[64,78,812,.2]])
        self.assertEqual(created["result"]["difference_matrix"],[[-26,-22,112,0]])
        code,detail=http(self.api.base,"/api/v1/soldiers/22-00000001")
        self.assertEqual(code,200)
        self.assertEqual(detail["result"],created["result"])
        code,receipt=http(self.api.base,"/api/v1/soldiers/22-00000001/module2",{})
        self.assertEqual(code,200)
        self.assertEqual(receipt["module2_response"]["status"],"accepted")
        self.assertEqual(receipt["module2_response"]["contract_version"],"2.0.0")

    def test_preview_not_saved_and_time_normalized(self):
        row=sample();row.pop("run_3km_seconds");row["run_3km_time"]="16:00"
        code,response=http(self.api.base,"/api/v1/evaluate",row)
        self.assertEqual(code,200)
        self.assertEqual(response["record"]["run_3km_seconds"],960)
        self.assertEqual(http(self.api.base,"/api/v1/soldiers")[1]["total"],5)

    def test_paging_search_missing_and_injection(self):
        code,data=http(self.api.base,"/api/v1/soldiers?page=2&page_size=2")
        self.assertEqual((code,len(data["items"]),data["total"]),(200,2,5))
        code,data=http(self.api.base,"/api/v1/soldiers?q=26-00000003")
        self.assertEqual((code,data["total"]),(200,1))
        self.assertEqual(http(self.api.base,"/api/v1/soldiers?q=%27%20OR%201%3D1--")[1]["total"],0)
        self.assertEqual(http(self.api.base,"/api/v1/soldiers?page_size=0")[0],422)
        self.assertEqual(http(self.api.base,"/api/v1/soldiers/99-99999999")[0],404)

    def test_json_boundary_and_origin(self):
        for raw in [b'{"age":20,"age":21}',b'{"age":NaN}',b'[]',b'{']:
            self.assertEqual(http(self.api.base,"/api/v1/evaluate",raw=raw)[0],400)
        code,_=http(self.api.base,"/api/v1/soldiers",sample(),
                    headers={"Content-Type":"application/json","Origin":"https://example.org"})
        self.assertEqual(code,403)

    def test_mock_rejects_tampered_contract(self):
        engine=Module1()
        envelope=engine.envelope(engine.evaluate(sample())[0],"tamper-test")
        envelope["module1_result"]["difference_matrix"][0][0]=-1
        self.assertEqual(http(self.mock.base,"/api/v1/plans",envelope)[0],422)

    def test_upstream_failure_propagates(self):
        self.mock.server.shutdown()
        self.mock.server.server_close()
        code,body=http(self.api.base,"/api/v1/soldiers/26-00000001/module2",{})
        self.assertIn(code,(502,504))
        self.assertIn(body["error"]["code"],("module2_unavailable","module2_timeout"))
        with self.api.server.store.connect() as db:
            self.assertEqual(db.execute("SELECT status FROM deliveries").fetchone()[0],"failed")

    def test_invalid_response_and_timeout(self):
        import time
        class Broken(JsonHandler):
            def route(self,method,url):
                if url.path=="/health":
                    self.send_json(200,{"status":"ok","mode":"real","contract_version":"wrong"})
                else:
                    self.send_bytes(200,b"not json","text/plain")
        with Running(serve(Broken,port=0)) as broken:
            client=Module2Client(broken.base,.1)
            for operation in [client.health,lambda:client.submit({"request_id":"x"})]:
                with self.assertRaises(DomainError) as error:operation()
                self.assertEqual(error.exception.code,"module2_invalid_response")
        class Slow(JsonHandler):
            def route(self,method,url):
                time.sleep(.15)
                self.send_json(200,{})
        with Running(serve(Slow,port=0)) as slow:
            with self.assertRaises(DomainError) as error:Module2Client(slow.base,.02).health()
            self.assertEqual(error.exception.code,"module2_timeout")

    def test_web_and_openapi_served(self):
        for path,text in [("/","군번"),("/app.js","soldier_id"),("/api/openapi.json","openapi")]:
            with urllib.request.urlopen(self.api.base+path) as response:
                self.assertEqual(response.status,200)
                self.assertIn(text,response.read().decode("utf-8"))


if __name__=="__main__":
    unittest.main(verbosity=2)
