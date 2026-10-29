// Host static-placer precision control, never RTL/placement/FPGA acceptance.
// Mirrors update_nets/wirelen_grad's centered weighted-average expressions.
// No coordinate clamp, omitted assertion, different objective or clock waiver.
#include <algorithm>
#include <cmath>
#include <cstdint>
#include <cstdlib>
#include <iostream>
#include <limits>
#include <random>
#include <stdexcept>
#include <string>
#include <vector>

struct Sums {
  double minimum = 0, maximum = 0, xminimum = 0, xmaximum = 0;
  std::vector<double> pminimum, pmaximum;
};

Sums evaluate(const std::vector<float>& locations, bool widened) {
  const auto bounds = std::minmax_element(locations.begin(), locations.end());
  const float center = (*bounds.first + *bounds.second) / 2.f;
  Sums s;
  for (float location : locations) {
    const float emin = (center - location) * 0.5f;
    const float emax = (location - center) * 0.5f;
    // The old expression returns float before assignment to a double field.
    const double lo = widened ? std::exp(static_cast<double>(emin)) : std::exp(emin);
    const double hi = widened ? std::exp(static_cast<double>(emax)) : std::exp(emax);
    s.pminimum.push_back(lo);
    s.pmaximum.push_back(hi);
    s.minimum += lo; s.maximum += hi;
    s.xminimum += location * lo; s.xmaximum += location * hi;
  }
  return s;
}

void require(bool condition, const char* text) {
  if (!condition) throw std::runtime_error(text);
}

double objective(const Sums& s) { return s.xmaximum / s.maximum - s.xminimum / s.minimum; }

std::vector<double> gradients(const std::vector<float>& locations, const Sums& s) {
  std::vector<double> values;
  for (std::size_t i = 0; i < locations.size(); ++i) {
    const float loc = locations[i];
    const double lo = (s.minimum * (s.pminimum[i] * (1.0f - 0.5f * loc)) +
                       0.5f * s.pminimum[i] * s.xminimum) / (s.minimum * s.minimum);
    const double hi = (s.maximum * (s.pmaximum[i] * (1.0f + 0.5f * loc)) -
                       0.5f * s.pmaximum[i] * s.xmaximum) / (s.maximum * s.maximum);
    require(std::isfinite(lo) && std::isfinite(hi), "nonfinite weighted-average derivative");
    values.push_back(lo - hi);
  }
  return values;
}

long double reference(const std::vector<float>& locations) {
  const auto bounds = std::minmax_element(locations.begin(), locations.end());
  const long double center = (*bounds.first + *bounds.second) / 2.f;
  long double lo = 0, hi = 0, xlo = 0, xhi = 0;
  for (float x : locations) {
    const long double low = std::exp((center - x) * 0.5L);
    const long double high = std::exp((x - center) * 0.5L);
    lo += low; hi += high; xlo += x * low; xhi += x * high;
  }
  return xhi / hi - xlo / lo;
}

void positive_case(const std::vector<float>& locations) {
  auto s = evaluate(locations, true);
  require(s.minimum > 0 && s.maximum > 0, "empty weighted average");
  for (auto value : s.pminimum) require(std::isfinite(value), "nonfinite minimum exponent");
  for (auto value : s.pmaximum) require(std::isfinite(value), "nonfinite maximum exponent");
  require(std::isfinite(s.xminimum) && std::isfinite(s.xmaximum), "nonfinite weighted sum");
  const double value = objective(s);
  require(std::isfinite(value), "nonfinite objective");
  require(std::abs(static_cast<long double>(value) - reference(locations)) <= 1e-9L,
          "changed centered weighted-average objective");
  const auto grad = gradients(locations, s);
  double sum = 0;
  for (auto v : grad) sum += v;
  require(std::abs(sum) < 1e-8, "translation-invariant gradient does not sum to zero");
}

int main(int argc, char** argv) {
  try {
    require(argc == 4, "expected mode width height");
    const int width = std::stoi(argv[2]), height = std::stoi(argv[3]);
    require(width == 327 && height == 417, "wrong qualified device grid");
    const std::vector<float> spanning{0.f, static_cast<float>(height - 1)};
    if (std::string(argv[1]) == "negative") {
      auto s = evaluate(spanning, false);
      require(!std::isfinite(s.pmaximum.back()), "old float overload unexpectedly finite");
      // Real rejected result, not a manufactured PASS from any nonzero exit.
      std::cerr << "EXPECTED_REJECT old_float_exp_overflow valid_grid_y=0..416 exponent=104\n";
      return 1;
    }
    require(std::string(argv[1]) == "positive", "unknown mode");
    positive_case(spanning);
    positive_case({0.f, static_cast<float>(width - 1)});
    positive_case({0.f, 416.f, 0.f, 416.f, 208.f});
    positive_case(std::vector<float>(100000, 208.f));
    std::mt19937 rng(0x3588e001u);
    for (int i = 0; i < 1024; ++i) {
      std::vector<float> locations;
      for (int j = 0; j < 2 + (i % 31); ++j) locations.push_back(float(rng() % height));
      positive_case(locations);
    }
    // Under the old finite range, both overloads represent the same objective.
    for (int i = 0; i < 1024; ++i) {
      std::vector<float> locations;
      for (int j = 0; j < 2 + (i % 31); ++j) locations.push_back(float(rng() % 101));
      const auto old = evaluate(locations, false), changed = evaluate(locations, true);
      require(std::isfinite(objective(old)), "old moderate-range objective unexpectedly nonfinite");
      require(std::abs(objective(old) - objective(changed)) < 2e-6, "finite-range objective differs");
    }
    std::cout << "PASS_STATIC_EXP_PRECISION_ONLY extreme_random_cases=1028 finite_range_cases=1024 seed=3588e001\n";
  } catch (const std::exception& error) {
    std::cerr << "FAIL_STATIC_EXP_PRECISION_ONLY " << error.what() << "\n";
    return 2;
  }
}
