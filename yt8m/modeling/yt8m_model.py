import tensorflow as tf
from official.vision.beta.projects.yt8m.configs import yt8m as yt8m_cfg
from official.vision.beta.projects.yt8m.modeling import yt8m_agg_models, yt8m_model_utils as utils
from official.modeling import tf_utils

layers = tf.keras.layers


class YT8MModel(tf.keras.Model):
    def __init__(self,
                 input_params: yt8m_cfg.YT8MModel,
                 num_frames=32,
                 num_classes=3862,
                 input_specs=layers.InputSpec(shape=[32, 1152]),
                 **kwargs):
        """YT8M initialization function.
          Args:
            input_params: model configuration parameters
            input_specs: Specifies the rank, dtype and shape of every input to a layer.
            **kwargs: keyword arguments to be passed.

        """

        self._self_setattr_tracking = False
        self._config_dict = {
            'input_specs': input_specs,
            'num_classes': num_classes,
            'num_frames': num_frames,
            'input_params': input_params
        }
        self._num_classes = num_classes
        self._num_frames = num_frames
        self._input_specs = input_specs
        self._act_fn = tf_utils.get_activation(input_params.activation)

        inputs = tf.keras.Input(shape=self._input_specs.shape)

        num_frames = tf.cast(tf.expand_dims([self._num_frames], 1), tf.float32)
        if input_params.sample_random_frames:
            model_input = utils.SampleRandomFrames(inputs, num_frames, input_params.iterations)
        else:
            model_input = utils.SampleRandomSequence(inputs, num_frames, input_params.iterations)

        max_frames = model_input.shape.as_list()[1]
        feature_size = model_input.shape.as_list()[2]
        print("---------------- YT8M_MODEL.PY ----------------")
        print("after SampleRandom---: ", model_input.shape) #[None, 30, 1152]
        print("---------------- YT8M_MODEL.PY ----------------")

        reshaped_input = tf.reshape(model_input, shape=[-1, feature_size])
        print("---------------- YT8M_MODEL.PY ----------------")
        print("after reshape [-1, feature_size]: ", reshaped_input.shape) #[None, 1152]
        print("---------------- YT8M_MODEL.PY ----------------")
        tf.summary.histogram("input_hist", reshaped_input)

        if input_params.add_batch_norm:
            reshaped_input = layers.BatchNormalization(name="input_bn",
                                                       scale=True,
                                                       center=True,
                                                       trainable=input_params.is_training)(reshaped_input)

            print("---------------- YT8M_MODEL.PY ----------------")
            print("layers.BatchNorm: ", reshaped_input.shape)
            print("---------------- YT8M_MODEL.PY ----------------")

        cluster_weights = tf.Variable(tf.random_normal_initializer(stddev=1 / tf.sqrt(tf.cast(feature_size, tf.float32)))(
            shape=[feature_size, input_params.cluster_size]),
            name="cluster_weights")

        tf.summary.histogram("cluster_weights", cluster_weights)
        activation = tf.linalg.matmul(reshaped_input, cluster_weights)

        if input_params.add_batch_norm:
            activation = layers.BatchNormalization(name="cluster_bn",
                                                   scale=True,
                                                   center=True,
                                                   trainable=input_params.is_training)(activation)

        else:
            cluster_biases = tf.Variable(
                tf.random_normal_initializer(stddev=1 / tf.math.sqrt(feature_size))(shape=[input_params.cluster_size]),
                name="cluster_biases")
            tf.summary.histogram("cluster_biases", cluster_biases)
            activation += cluster_biases

        activation = self._act_fn(activation)
        tf.summary.histogram("cluster_output", activation)

        activation = tf.reshape(activation, [-1, max_frames, input_params.cluster_size])
        activation = utils.FramePooling(activation, input_params.pooling_method)

        hidden1_weights = tf.Variable(tf.random_normal_initializer(stddev=1 / tf.sqrt(tf.cast(input_params.cluster_size, tf.float32)))(
            shape=[input_params.cluster_size, input_params.hidden_size]),
            name="hidden1_weights")

        tf.summary.histogram("hidden1_weights", hidden1_weights)
        activation = tf.linalg.matmul(activation, hidden1_weights)

        if input_params.add_batch_norm:
            activation = layers.BatchNormalization(name="hidden1_bn",
                                                   scale=True,
                                                   center=True,
                                                   trainable=input_params.is_training)(activation)


        else:
            hidden1_biases = tf.Variable(tf.random_normal_initializer(stddev=0.01)(shape=[input_params.hidden_size]),
                                         name="hidden1_biases")

            tf.summary.histogram("hidden1_biases", hidden1_biases)
            activation += hidden1_biases

        activation = self._act_fn(activation)
        tf.summary.histogram("hidden1_output", activation)

        aggregated_model = getattr(yt8m_agg_models,
                                   input_params.yt8m_agg_classifier_model)
        output = aggregated_model().create_model(model_input=activation,
                                                 vocab_size=self._num_classes)

        super(YT8MModel, self).__init__(inputs=inputs, outputs=output.get("predictions"), **kwargs)

    @property
    def checkpoint_items(self):
        """Returns a dictionary of items to be additionally checkpointed."""
        return dict(backbone=self.backbone)

    def get_config(self):
        return self._config_dict

    @classmethod
    def from_config(cls, config, custom_objects=None):
        return cls(**config)
