python3 -m venv venv
source venv/bin/activate
python -m pip install bitgn-api-connectrpc-python --extra-index-url https://buf.build/gen/python
python -m pip install bitgn-api-grpc-python --extra-index-url https://buf.build/gen/python
python -m pip install bitgn-api-protocolbuffers-python --extra-index-url https://buf.build/gen/python
python -m pip install -r requirements.txt
python -m pip install --upgrade protobuf
