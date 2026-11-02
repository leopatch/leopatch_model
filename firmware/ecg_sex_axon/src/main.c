/*
 * ECG sex classifier on the nRF54LM20B: the CPU runs the front end (stem + max-pool),
 * the Axon NPU runs the rest. Runs the test ECGs embedded by deploy/export_axon_model.py
 * and checks the results against the Python int8 reference.
 */
#include <assert.h>
#include <math.h>

#include <zephyr/kernel.h>
#include <zephyr/logging/log.h>

#include <axon/nrf_axon_platform.h>
#include <drivers/axon/nrf_axon_driver.h>
#include <drivers/axon/nrf_axon_nn_infer.h>

#include "frontend.h"
#include "generated/nrf_axon_model_ecg_sex_v3_.h"
#include "generated/test_ecgs.h"

LOG_MODULE_REGISTER(ecg_sex);

#define MODEL model_ecg_sex_v3

/* Allowed logit difference to the Python int8 reference (front end float rounding). */
#define LOGIT_TOLERANCE 0.25f

static int8_t npu_input[FRONTEND_OUT_CH * FRONTEND_OUT_LEN];
static int8_t npu_output[NRF_AXON_MODEL_ECG_SEX_V3_PACKED_OUTPUT_SIZE] __aligned(4);

static float dequantize(int8_t q, const nrf_axon_compiled_model_output_s *out)
{
	return (float)(q - out->dequant_zp) * ldexpf((float)out->dequant_mult, -out->dequant_round);
}

int main(void)
{
	const nrf_axon_nn_compiled_model_input_s *in = &MODEL.inputs[0];
	const nrf_axon_nn_model_layer_dimensions_s *dims = &in->dimensions;
	nrf_axon_result_e result;
	int passed = 0;

	LOG_INF("ECG sex classifier, model %s on Axon NPU", MODEL.model_name);

	if (dims->height * dims->width * dims->channel_cnt != sizeof(npu_input) ||
	    dims->byte_width != 1 || MODEL.outputs[0].dimensions.byte_width != 1) {
		LOG_ERR("Model input/output does not match the front end");
		return -1;
	}

	result = nrf_axon_platform_init();
	if (result != NRF_AXON_RESULT_SUCCESS) {
		LOG_ERR("Axon NPU platform initialization failed, err %d", result);
		return -1;
	}

	if (nrf_axon_nn_model_init_vars(&MODEL)) {
		LOG_ERR("Model persistent variables initialization failed");
		return -1;
	}

	result = nrf_axon_nn_model_validate(&MODEL);
	if (result != NRF_AXON_RESULT_SUCCESS) {
		LOG_ERR("Model validation failed, err %d", result);
		return -1;
	}

	const float inv_scale = ldexpf((float)in->quant_mult, -in->quant_round);

	for (int i = 0; i < TEST_ECG_COUNT; i++) {
		const uint32_t t0 = k_cycle_get_32();

		frontend_run(test_ecg[i], npu_input, inv_scale, in->quant_zp);

		const uint32_t t1 = k_cycle_get_32();

		result = nrf_axon_nn_model_infer_sync(&MODEL, npu_input, npu_output);

		const uint32_t t2 = k_cycle_get_32();

		if (result != NRF_AXON_RESULT_SUCCESS) {
			LOG_ERR("Inference failed, err %d", result);
			return -1;
		}

		const float logit = dequantize(npu_output[0], &MODEL.outputs[0]);
		const float prob = 1.0f / (1.0f + expf(-logit));
		const bool ok = fabsf(logit - test_ecg_logit_int8[i]) <= LOGIT_TOLERANCE;

		passed += ok;
		LOG_INF("ECG %d: p(label 1) %.3f -> label %d | logit %.3f, int8 ref %.3f, float ref %.3f %s",
			i, (double)prob, prob >= MODEL_VAL_THRESHOLD, (double)logit,
			(double)test_ecg_logit_int8[i], (double)test_ecg_logit_float[i],
			ok ? "OK" : "MISMATCH");
		LOG_INF("       CPU front end %u ms, NPU %u ms", k_cyc_to_ms_near32(t1 - t0),
			k_cyc_to_ms_near32(t2 - t1));
	}

	LOG_INF("%d/%d ECGs match the Python reference", passed, TEST_ECG_COUNT);
	return 0;
}
