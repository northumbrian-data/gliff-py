import os
import gliff
from decouple import UndefinedValueError


def test_get_value():
    # check we get an error when there is no variable at all
    try:
        gliff.get_value("TEST_VARIABLE")
    except UndefinedValueError as e:
        print(e)
        assert str(e) == "TEST_VARIABLE not found."
    
    # check we get a value when there is an env variable but no local
    # FIXME
    # os.environ["TEST_VARIABLE"] = "test_value"
    # assert gliff.get_value("TEST_VARIABLE") == "test_value"

    # check we get a value when there is a local variable
    # FIXME
    # TEST_VARIABLE = "local_test_value"
    # assert gliff.get_value("TEST_VARIABLE") == "local_test_value"
