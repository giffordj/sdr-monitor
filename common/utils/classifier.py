import ai_edge_litert.interpreter
import numpy as np


class Classifier:
    def __init__(self, model_path, labels):
        self.__interpreter = ai_edge_litert.interpreter.Interpreter(model_path=model_path)
        self.__labels = labels

    def predict(self, data):
        self.__interpreter.resize_tensor_input(0, data.shape)
        self.__interpreter.allocate_tensors()

        input_details = self.__interpreter.get_input_details()
        output_details = self.__interpreter.get_output_details()

        self.__interpreter.set_tensor(input_details[0]["index"], data)
        self.__interpreter.invoke()

        output = self.__interpreter.get_tensor(output_details[0]["index"])
        return np.argmax(output, axis=1)

    def predict_class(self, data):
        predicted_classes = self.predict(data)
        counts = np.bincount(predicted_classes)
        top_class = np.argmax(counts)
        return (top_class, self.__labels[top_class], counts[top_class] / predicted_classes.size)
