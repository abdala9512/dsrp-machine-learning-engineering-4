import litserve as ls

from pydantic import BaseModel


class DSRPRequest(BaseModel):
    x: int


class InferenceEngine(ls.LitAPI):
    def setup(self, device):
        self.text_model = lambda x: x**2
        self.vision_model = lambda x: x**3


    def decode_request(self, request: dict) -> DSRPRequest:
        print(request)
        return  DSRPRequest(
            x=request["input"] 
        )

    def predict(self, request: DSRPRequest ):

        x = request.x
        # perform calculations using both models
        a = self.text_model(x)
        b = self.vision_model(x)
        c = a + b
        return c

    def encode_response(self, output):
        return {"output": output} 

if __name__ == "__main__":
    engine = InferenceEngine()
    server = ls.LitServer(engine, accelerator="auto",)
    server.run(port=8000,)